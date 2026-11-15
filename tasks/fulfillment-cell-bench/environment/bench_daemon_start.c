#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#ifdef __APPLE__
extern char **environ;
static int setresgid(gid_t r, gid_t e, gid_t s) { (void)s; return (setregid(r, e) == 0 && setgid(e) == 0) ? 0 : -1; }
static int setresuid(uid_t r, uid_t e, uid_t s) { (void)s; return (setreuid(r, e) == 0 && setuid(e) == 0) ? 0 : -1; }
static int clearenv(void) {
    static char *empty_env[] = { NULL };
    environ = empty_env;
    return 0;
}
#endif

static int try_connect_sock(const char *sock_path) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }
    (void)fcntl(fd, F_SETFD, FD_CLOEXEC);
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    int written = snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", sock_path);
    if (written < 0 || written >= (int)sizeof(addr.sun_path)) {
        close(fd);
        return -1;
    }
    int rc = connect(fd, (struct sockaddr *)&addr, sizeof(addr));
    close(fd);
    return rc;
}

static int sock_ready(const char *sock_path) {
    struct stat st;
    if (lstat(sock_path, &st) != 0) {
        return 0;
    }
    if (!S_ISSOCK(st.st_mode)) {
        return 0;
    }
    if ((st.st_mode & (S_IRWXU | S_IRWXG | S_IRWXO)) != 0666) {
        return 0;
    }
    return try_connect_sock(sock_path) == 0;
}

static int ensure_dir(const char *path, mode_t mode) {
    if (mkdir(path, mode) != 0 && errno != EEXIST) {
        return -1;
    }
    struct stat lst;
    if (lstat(path, &lst) != 0 || S_ISLNK(lst.st_mode) || !S_ISDIR(lst.st_mode)) {
        return -1;
    }
    int dirfd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dirfd < 0) {
        return -1;
    }
    struct stat fst;
    if (fstat(dirfd, &fst) != 0 || !S_ISDIR(fst.st_mode)) {
        close(dirfd);
        return -1;
    }
    if (fchown(dirfd, 0, 0) != 0 || fchmod(dirfd, mode) != 0) {
        close(dirfd);
        return -1;
    }
    close(dirfd);
    return 0;
}

int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) {
        fprintf(stderr, "bench-daemon-start takes no arguments\n");
        return 2;
    }

    if (setresgid(0, 0, 0) != 0) {
        perror("setresgid");
        return 1;
    }
    if (setresuid(0, 0, 0) != 0) {
        perror("setresuid");
        return 1;
    }
    umask(0022);
    sigset_t empty_mask;
    if (sigemptyset(&empty_mask) == 0) {
        (void)sigprocmask(SIG_SETMASK, &empty_mask, NULL);
    }
    struct rlimit inf_lim = { RLIM_INFINITY, RLIM_INFINITY };
    (void)setrlimit(RLIMIT_FSIZE, &inf_lim);
    (void)setrlimit(RLIMIT_CPU, &inf_lim);
#ifdef __linux__
    (void)close_range(3, ~0U, 0);
#else
    for (int fd = 3; fd < 1024; ++fd) {
        (void)close(fd);
    }
#endif
    if (clearenv() != 0) {
        perror("clearenv");
        return 1;
    }
    if (setenv("PATH", "/usr/local/bin:/usr/bin:/bin", 1) != 0 ||
        setenv("HOME", "/root", 1) != 0 ||
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1) != 0) {
        perror("setenv");
        return 1;
    }

    if (ensure_dir("/run", 0755) != 0 || ensure_dir("/run/bench", 0755) != 0) {
        perror("mkdir /run/bench");
        return 1;
    }
    if (ensure_dir("/logs", 0755) != 0 || ensure_dir("/logs/artifacts", 0755) != 0 || ensure_dir("/logs/verifier", 0755) != 0) {
        perror("mkdir /logs/artifacts");
        return 1;
    }

    const char *sock_path = "/run/bench/bench.sock";
    if (sock_ready(sock_path)) {
        return 0;
    }

    int lock_fd = open("/run/bench/daemon.lock", O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (lock_fd < 0) {
        perror("open daemon.lock");
        return 1;
    }
    if (flock(lock_fd, LOCK_EX) != 0) {
        perror("flock");
        close(lock_fd);
        return 1;
    }
    if (sock_ready(sock_path)) {
        close(lock_fd);
        return 0;
    }

    (void)unlink(sock_path);

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        close(lock_fd);
        return 1;
    }
    if (pid == 0) {
        if (setsid() < 0) {
            _exit(1);
        }
        if (chdir("/srv/bench_daemon") != 0) {
            _exit(1);
        }
        int devnull = open("/dev/null", O_RDONLY);
        if (devnull >= 0) {
            if (dup2(devnull, STDIN_FILENO) < 0) {
                _exit(1);
            }
            if (devnull > STDERR_FILENO) {
                close(devnull);
            }
        }
        int logfd = open("/srv/bench_daemon/daemon.log", O_CREAT | O_WRONLY | O_APPEND | O_NOFOLLOW, 0600);
        if (logfd >= 0) {
            if (dup2(logfd, STDOUT_FILENO) < 0 || dup2(logfd, STDERR_FILENO) < 0) {
                _exit(1);
            }
            if (logfd > STDERR_FILENO) {
                close(logfd);
            }
        }
        char *const daemon_argv[] = {
            "/usr/local/bin/python3",
            "-I",
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "quarterly",
            "--socket",
            "/run/bench/bench.sock",
            "--state",
            "/srv/bench_daemon/state.json",
            "--submission",
            "/logs/artifacts/submission.json",
            "--log",
            "/logs/artifacts/episode.json",
            NULL
        };
        execv("/usr/local/bin/python3", daemon_argv);
        _exit(127);
    }

    for (int i = 0; i < 200; ++i) {
        if (sock_ready(sock_path)) {
            close(lock_fd);
            return 0;
        }
        int status = 0;
        pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            fprintf(stderr, "bench-daemon-start: daemon exited prematurely\n");
            close(lock_fd);
            return 1;
        }
        usleep(25000);
    }

    if (sock_ready(sock_path)) {
        close(lock_fd);
        return 0;
    }
    fprintf(stderr, "bench-daemon-start: timed out waiting for %s\n", sock_path);
    close(lock_fd);
    return 1;
}

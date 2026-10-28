/*
 * Profile launcher based on jeroenwollaars/claude-dual-launcher (MIT).
 * See LICENSE in this directory. Uses the installed, unmodified Claude app.
 */
#include <errno.h>
#include <limits.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
#ifndef PROFILE_DIR
#error "PROFILE_DIR must be set at compile time"
#endif
#ifndef APP_BINARY
#define APP_BINARY "/Applications/Claude.app/Contents/MacOS/Claude"
#endif

/* No shell interpolation. Escape regex characters and require a path boundary,
 * so the default Claude profile does not also match Claude-Official. */
static int running(const char *argument) {
    char pattern[PATH_MAX * 3];
    size_t used = 0;
    for (const char *p = argument; *p; p++) {
        if (used + 3 >= sizeof pattern) return -1;
        if (strchr(".[]{}()\\*+?^$|", *p)) pattern[used++] = '\\';
        pattern[used++] = *p;
    }
    if (used + sizeof("($|[[:space:]])") > sizeof pattern) return -1;
    strcpy(pattern + used, "($|[[:space:]])");
    char *args[] = {"pgrep", "-qf", "--", pattern, NULL};
    pid_t child;
    int status;
    if (posix_spawn(&child, "/usr/bin/pgrep", NULL, NULL, args, environ)) return -1;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return -1;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) > 1) return -1;
    return WEXITSTATUS(status) == 0;
}

static int clean_environment(void) {
    for (size_t i = 0; environ[i];) {
        char *key = strdup(environ[i]);
        if (!key) return -1;
        char *end = strchr(key, '=');
        if (end) *end = '\0';
        int remove = !strncmp(key, "ANTHROPIC_", 10)
            || !strncmp(key, "CLAUDE_CODE_", 12)
            || !strcmp(key, "CLAUDE_CONFIG_DIR")
            || !strcmp(key, "CLAUDE_USER_DATA_DIR")
            || !strcmp(key, "CLAUDE_AI_URL");
        if (remove) unsetenv(key); else i++;
        free(key);
    }
    return 0;
}

int main(int argc, char **argv) {
    const char *home = getenv("HOME");
    if (!home || home[0] != '/') { fputs("HOME must be absolute.\n", stderr); return 2; }
    char directory[PATH_MAX + 32];
    int length = snprintf(directory, sizeof directory,
        "--user-data-dir=%s/Library/Application Support/%s", home, PROFILE_DIR);
    if (length < 0 || (size_t)length >= sizeof directory) return 2;
    int found = running(directory);
    if (found < 0) { fputs("Cannot check running profile.\n", stderr); return 2; }
    if (found) return 0;
#ifdef THIRD_PARTY_PROFILE
    /* The default app can start without a flag and move helpers to Claude-3p. */
    char alternate[PATH_MAX + 32];
    length = snprintf(alternate, sizeof alternate,
        "--user-data-dir=%s/Library/Application Support/Claude-3p", home);
    if (length < 0 || (size_t)length >= sizeof alternate) return 2;
    found = running(alternate);
    if (found < 0) return 2;
    if (found) return 0;
#endif
    if (clean_environment() < 0) return 2;
    char *args[argc + 2];
    args[0] = APP_BINARY;
    args[1] = directory;
    for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
    args[argc + 1] = NULL;
    execv(args[0], args);
    perror("Cannot start Claude Desktop");
    return 1;
}

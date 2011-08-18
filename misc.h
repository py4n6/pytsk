#include <assert.h>

#define BUFF_SIZE 40960

#ifdef WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <io.h>
#include <stdio.h>
#define MSG_NOSIGNAL 0
typedef  unsigned long int in_addr_t;
#include <stdint.h>
typedef int bool;
#else

#include <sys/socket.h>
#include <netinet/tcp.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <time.h>
#include <libgen.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>

#define O_BINARY 0
typedef int bool;

#endif


#define strndup rep_strndup
char *rep_strndup(const char *s, size_t n);

#define strnlen rep_strnlen
size_t rep_strnlen(const char *s, size_t n);


#ifndef MIN
#define MIN(a,b) ((a)<(b)?(a):(b))
#endif

#ifndef MAX
#define MAX(a,b) ((a)>(b)?(a):(b))
#endif

#ifdef HAVE_INTTYPES_H
#include <inttypes.h>
#endif

#define true 1
#define false 0

#ifndef HAVE_HTONLL
uint64_t htonll(uint64_t n);
#define ntohll(x) htonll(x)
#endif

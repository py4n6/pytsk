#include <assert.h>


  // Visual Studio defines.
#ifdef _MSC_VER

#define inline __inline
#define DLL_PUBLIC __declspec(dllexport)
#define UNUSED

#ifdef MS_WIN64
typedef __int64 ssize_t;
#else
typedef _W64 int ssize_t;
#endif

#else

#ifdef min
#undef min
#endif
#define min(X, Y)  ((X) < (Y) ? (X) : (Y))

#ifdef max
#undef max
#endif
#define max(X, Y)  ((X) > (Y) ? (X) : (Y))

#define UNUSED __attribute__((unused))


#ifndef HEADERS_ONLY
#define DLL_PUBLIC __attribute__ ((visibility("default")))
#else
#define DLL_PUBLIC
#endif

#endif     // ifdef _MSC_VER

#ifdef WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <io.h>
#include <stdio.h>
#define MSG_NOSIGNAL 0
typedef  unsigned long int in_addr_t;
#include <stdint.h>
typedef int bool;

#define inline
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

/* Miscellaneous definitions.
 *
 * Copyright 2010, Michael Cohen <sucdette@gmail.com>.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#ifndef _PYTSK_MISC_H
#define _PYTSK_MISC_H

#include <assert.h>

#if defined( HAVE_INTTYPES_H )
#include <inttypes.h>
#elif !defined( _MSC_VER )
#include <stdint.h>
#endif

#if defined( WIN32 )
#include <winsock2.h>
#include <ws2tcpip.h>
#include <io.h>
#include <stdio.h>

#else
/* sys/types.h needs to be included before sys/socket.h on
 * some platforms like FreeBSD.
 */
#include <sys/types.h>

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
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>

#endif /* defined( WIN32 ) */

#ifdef __cplusplus
extern "C" {
#endif

#if defined( _MSC_VER )
#define DLL_PUBLIC __declspec(dllexport)
#elif !defined( HEADERS_ONLY )
#define DLL_PUBLIC __attribute__ ((visibility("default")))
#else
#define DLL_PUBLIC
#endif

/* Used by class parser */
#if defined( _MSC_VER )
#define UNUSED
#else
#define UNUSED __attribute__((unused))
#endif

#if !defined( PYTSK3_ATTRIBUTE_UNUSED )
#if defined( __GNUC__ ) && __GNUC__ >= 3
#define PYTSK3_ATTRIBUTE_UNUSED  __attribute__ ((__unused__))
#else
#define PYTSK3_ATTRIBUTE_UNUSED
#endif
#endif

#if defined( _MSC_VER )
#define PYTSK3_UNREFERENCED_PARAMETER( parameter ) \
	UNREFERENCED_PARAMETER( parameter );
#else
#define PYTSK3_UNREFERENCED_PARAMETER( parameter ) \
	/* parameter */
#endif

#if !defined( _MSC_VER )
#ifdef min
#undef min
#endif
#define min(X, Y)  ((X) < (Y) ? (X) : (Y))

#ifdef max
#undef max
#endif
#define max(X, Y)  ((X) > (Y) ? (X) : (Y))

#endif /* if !defined( _MSC_VER ) */

#ifndef MIN
#define MIN(a,b) ((a)<(b)?(a):(b))
#endif

#ifndef MAX
#define MAX(a,b) ((a)>(b)?(a):(b))
#endif

#if defined( _MSC_VER )
#if !defined( HAVE_SSIZE_T )
#define HAVE_SSIZE_T

#if defined( MS_WIN64 )
typedef __int64 ssize_t;
#else
typedef _W64 int ssize_t;
#endif

#endif /* !defined( HAVE_SSIZE_T ) */
#endif /* defined( _MSC_VER ) */

#if defined( WIN32 )
#define MSG_NOSIGNAL 0
typedef  unsigned long int in_addr_t;
#else
#define O_BINARY 0
#endif

#define true 1
#define false 0

#ifdef __cplusplus
}
#endif

#endif


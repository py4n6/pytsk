/* AFF4 error functions.
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
#ifndef AFF4_ERRORS_H_
#define AFF4_ERRORS_H_

#include "class.h"

#ifdef __cplusplus
extern "C" {
#endif

// Some helpful little things
#define ERROR_BUFFER_SIZE 1024

/** This is used for error reporting. This is similar to the way
    python does it, i.e. we set the error flag and return NULL.
*/
#define  EZero             0
#define  EGeneric          1
#define  EOverflow         2
#define  EWarning          3
#define  EUnderflow        4
#define  EIOError          5
#define  ENoMemory         6
#define  EInvalidParameter 7
#define  ERuntimeError     8
#define  EKeyError         9
  // Reserved for impossible conditions
#define  EProgrammingError 10

DLL_PUBLIC void *aff4_raise_errors(int t, const char *string,  ...);

/** We only set the error state if its not already set */
#define RaiseError(t, message, ...)                                     \
  aff4_raise_errors(t, "%s: (%s:%d) " message, __FUNCTION__, __FILE__, __LINE__, ## __VA_ARGS__);

#define LogWarnings(format, ...)		\
  do {						\
    RaiseError(EWarning, format, ## __VA_ARGS__);	\
    PrintError();				\
  } while(0);

#define ClearError()				\
  do {*aff4_get_current_error(NULL) = EZero;} while(0);

#define PrintError()				\
  do {char *error_str; if(*aff4_get_current_error(&error_str)) fprintf(stdout, "%s", error_str); fflush(stdout); ClearError(); }while(0);

#define CheckError(error)			\
  (*aff4_get_current_error(NULL) == error)

/** The current error state is returned by this function.

    This is done in a thread safe manner.
 */
DLL_PUBLIC int *aff4_get_current_error(char **error_str);


// These macros are used when we need to do something which might
// change the error state on the error path of a function.
#define PUSH_ERROR_STATE { int *tmp_error_p = aff4_get_current_error(NULL); int tmp_error = *tmp_error_p; int exception __attribute__((unused));

#define POP_ERROR_STATE *tmp_error_p = tmp_error;};

#ifdef __cplusplus
} /* closing brace for extern "C" */
#endif

#endif /* !AFF4_ERRORS_H_ */

/* Error functions.
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
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "aff4_errors.h"
#include "class.h"

#define ERROR_BUFF_SIZE 10240

/* Per-thread error state. Use C++11 thread_local storage class to 
 * guarantee each thread gets its own zero-initialized copy, so
 * raising or inspecting errors never races across threads on any
 * supported platform.
 */
static thread_local char tls_error_buffer[ERROR_BUFF_SIZE];
static thread_local int tls_error_type = 0;

DLL_PUBLIC int *aff4_get_current_error(char **error_buffer) {
  if(error_buffer != NULL) {
    *error_buffer = tls_error_buffer;
  };
  return &tls_error_type;
};

DLL_PUBLIC void *aff4_raise_errors(int t, const char *reason, ...) {
  char *error_buffer;
  char tmp[ERROR_BUFF_SIZE];
  int *type = aff4_get_current_error(&error_buffer);

  /* Always leave tmp as a valid C string: vsnprintf is skipped when
   * reason is NULL, and strncat below reads from tmp unconditionally.
   */
  tmp[0] = 0;

  if(reason) {
    va_list ap;
    va_start(ap, reason);

    vsnprintf(tmp, ERROR_BUFF_SIZE-1, reason, ap);
    tmp[ERROR_BUFF_SIZE-1] = 0;
    va_end(ap);
  };

  if(*type == EZero) {
    *error_buffer = 0;

    //update the error type
    *type = t;
  } else {
    strncat(error_buffer, "\n", ERROR_BUFF_SIZE -1 );
  };

  strncat(error_buffer, tmp, ERROR_BUFF_SIZE-1);

  return NULL;
};

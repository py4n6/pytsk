/* C class and object types functions.
 *
 * Copyright 2013, Michael Cohen <sucdette@gmail.com>.
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
#include "misc.h"
#include "class.h"

#define BUFF_SIZE 1024

// Noone should instantiate Object directly. this should be already
// allocated therefore:

DLL_PUBLIC PYTSK_INLINE void Object_init(Object this) {
  this->__class__ = &__Object;
  this->__super__ = NULL;
};

struct Object_t __Object = {
  &__Object,                 //.__class__
  &__Object,                 //.__super__
  "Object",                  //.__name__
  "",                        //.__doc__
  sizeof(struct Object_t),   //.__size
  NULL   //.__extension
};

int issubclass(Object obj, Object class) {
  obj = obj->__class__;
  while(1) {
    if(obj == class->__class__)
      return 1;

    obj=obj->__super__;

    if(obj == &__Object || obj==NULL)
      return 0;
  };
};

void unimplemented(Object self) {
  printf("%s contains unimplemented functions.. is it an abstract class?\n", NAMEOF(self));
  abort();
};

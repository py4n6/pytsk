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
#ifndef __CLASS_H__
#define __CLASS_H__

/*
  Classes and objects in C

  This file makes it easy to implement classes and objects in C. To
  define a class we need to perform three steps:

  Define the class prototype. This is suitable to go in a .h file for
  general use by other code.

  Note all classes extend Object.

  Example::

CLASS(Foo, Object)
    int x;
    int y;

    //This declares a method of a class Foo, called Con returning a
    //Foo object. In other words it is a constructor.
    Foo METHOD(Foo, Con, int x, int y);
    int METHOD(Foo, add);

END_CLASS

Now we need to define some functions for the constructor and
methods. Note that the constuctor is using ALLOCATE_CLASS to allocate
space for the class structures. Callers may call with self==NULL to
force allocation of a new class. Note that we do not call the
constructor of our superclass implicitly here. (Calling the sperclass
constructor is optional, but ALLOCATE_CLASS is not.).

Foo Foo_Con(Foo self,int x,int y) {
  self->x = x;
  self->y = y;

  return self;
};

int Foo_add(Foo this) {
  return (this->x + this->y);
};

Now we need to define the Virtual function table - These are those
functions and attributes which are defined in this class (over its
superclass). Basically these are all those things in the class
definition above, with real function names binding them. (Note that by
convention we preceed the name of the method with the name of the
class):

VIRTUAL(Foo,Object)
   VMETHOD(Con) = Foo_Con;
   VMETHOD(add) = Foo_add;
END_VIRTUAL

We can use inheritance too:

CLASS(Bar, Foo)
   Bar METHOD(Bar, Con, char *something)
END_CLASS

Here Bar extends Foo and defines a new constructor with a different prototype:

VIRTUAL(Bar,Foo)
   VMETHOD(Con) = Bar_Con
END_VIRTUAL

If there is a function which expects a Foo, we will need to over ride
the Foo constructor in the Bar, so the function will not see the
difference between the Foo and Bar:

CLASS(Bar,Foo)
  int bar_attr;
END_CLASS

Foo Bar_Con(Foo self, int x, int y) {
...
}

VIRTUAL(Bar, Foo)
  VMETHOD(super.Con) = Bar_Con
END_VIRTUAL

Note that in this case we are over riding the Con method defined in
Foo while creating derived Bar classes. The notation in the VIRTUAL
table is to use super.Con, because Foo's Con method (the one we are
over riding), can be located by using super.Con inside a Bar object.

Imagine now that in Bar_Con we wish to use methods and attributes
defined in Bar. Since Bar_Con over rides Bar's base class (Foo) it
must have the prototype described above. Since self is of type Foo its
impossible to use self->bar_attr (There is no bar_attr in Foo - its in
Bar).

In this case, we need to make a type cast to convice C that self is
actually a Bar not a Foo:

Foo Bar_Con(Foo self, int x, int y) {
   Bar this = (Bar)self;

   this->bar_attr=1
};

This allows us to access bars attributes.

This is a general oddity with C style classes, which C++ and Java
hide. In C we must always know which class defines which method and
attribute and reference the right class's method. So for example if we
want to call a Bar's add method:

Bar a;

a->super.add()

because add is defined in Bar's super class (Foo). Constract this with
C++ or Java which hide where methods are defined and simply make all
methods appear like they were defined inside the derived class. This
takes a while to get used to but the compiler will ensure that the
references are correct - otherwise things will generally not compile
properly.

This difference can be used for good and bad. It is possible in C to
call the base class's version of the method at any time (despite the
fact it was over ridden).

For example:

CLASS(Derived, Foo)
      int METHOD(Derived, add);
END_CLASS

VIRTUAL(Derived, Foo)
   VMETHOD(add) = Derived_add
END_VIRTUAL

If d is a Derived object, we can call Foo's version like this:
d->super.add()

But Derived's version is accessed by:
d->add()

Sometimes a derived class may want to over ride the base class's
methods as well, in this case the VIRTUAL section should over ride
super.add as well.

*/
#ifdef __cplusplus
extern "C" {
#endif

#include "misc.h"

#include <talloc.h>

#define CLASS(class,super_class)                                        \
  typedef struct class ## _t *class;                                    \
  DLL_PUBLIC class alloc_ ## class(void); /* Allocates object memory */ \
  DLL_PUBLIC int class ## _init(Object self); /* Class initializer */   \
  DLL_PUBLIC extern struct class ## _t __ ## class; /* Public class template */ \
  struct class ## _t {                                                  \
  struct super_class ## _t super;  /* Superclass Fields we inherit */   \
  class   __class__;       /* Pointer to our own class */               \
  super_class  __super__;  /* Pointer to our superclass */

#define METHOD(cls, name, ... )		\
  (* name)(cls self, ## __VA_ARGS__ )

  // Class methods are attached to the class but are not called with
  // an instance. This is similar to the python class method or java
  // static methods.
#define CLASS_METHOD(name, ... )                \
  (*name)(__VA_ARGS__)

/* This is a convenience macro which may be used if x if really large */
#define CALL(x, method, ... )			\
  (x)->method((x), ## __VA_ARGS__)

#define END_CLASS };

/* This is used to set the classes up for use:
 *
 * class_init = checks the class template (__class) to see if it has
 * been allocated. otherwise allocates it in the global context.
 *
 * class_Alloc = Allocates new memory for an instance of the
 * class. This is a recursive function calling each super class in
 * turn and setting the currently over ridden defaults. So for eample
 * suppose this class (foo) derives from bar, we first fill the
 * template with bars methods, and attributes. Then we over write
 * those with foos methods and attributes.
 */
#define VIRTUAL(class,superclass)                                       \
  struct class ## _t __ ## class;                                       \
                                                                        \
  DLL_PUBLIC  class alloc_ ## class(void) {				\
    class result = talloc_memdup(NULL, &__## class, sizeof(__## class)); \
    return result;                                                      \
  };                                                                    \
                                                                        \
  DLL_PUBLIC int class ## _init(Object this) {                          \
  class self = (class)this;                                             \
  if(self->__super__) return 1;                                         \
  superclass ##_init(this);                                             \
  this->__class__ = (Object)&__ ## class;                               \
  self->__class__ = (class)&__ ## class;                               \
  this->__super__ = (Object)&__ ## superclass;                          \
  self->__super__ = (superclass)&__ ## superclass;                      \
  this->__size = sizeof(struct class ## _t);                            \
  this->__name__ = #class;

#define SET_DOCSTRING(string)			\
  ((Object)self)->__doc__ = string

#define END_VIRTUAL return 1; };

#define VMETHOD(method)				\
  (self)->method

#define VMETHOD_BASE(base, method)		\
  (((base)self)->method)

#define CLASS_ATTR(self, base, method)		\
  (((base)self)->method)

#define VATTR(attribute)			\
  (self)->attribute

#define NAMEOF(obj)				\
  ((Object)obj)->__name__

#define SIZEOF(obj)                             \
  ((Object)obj)->__size

#define DOCSTRING(obj)				\
  ((Object)obj)->__doc__

#define INIT_CLASS(class)                       \
  class ## _init((Object)&__ ## class)

/* This MACRO is used to construct a new Class using a constructor.
 *
 * This is done to try and hide the bare (unbound) method names in
 * order to prevent name space pollution. (Bare methods may be
 * defined as static within the implementation file). This macro
 * ensures that class structures are initialised properly before
 * calling their constructors.
 *
 * We require the following args:
 *  class - the type of class to make
 *  virt_class - The class where the method was defined
 *  constructors - The constructor method to use
 *  context - a talloc context to use.
 *
 *  Note that the class and virt_class do not have to be the same if
 *  the method was not defined in the current class. For example
 *  suppose Foo extends Bar, but method is defined in Bar but
 *  inherited in Foo:
 *
 *  CONSTRUCT(Foo, Bar, super.method, context)
 *
 *  virt_class is Bar because thats where method was defined.
 */

// The following only initialises the class if the __super__ element
// is NULL. This is fast as it wont call the initaliser unnecessaily
#if 0
#define CONSTRUCT(class, virt_class, constructor, context, ... )        \
  (class)( __## class.__super__ == NULL ?                               \
           class ## _init((Object)&__ ## class) : 0,                    \
           __## virt_class.__super__ == NULL ?                          \
           virt_class ## _init((Object)&__ ## virt_class): 0,           \
             ((virt_class)(&__ ## class))->constructor(                 \
                       (virt_class)_talloc_memdup(context, &__ ## class, sizeof(struct class ## _t),  __location__ "(" #class ")"), \
				   ## __VA_ARGS__) )
#endif

  // This requires the class initializers to have been called
  // previously. Therefore they are not exported.
#define CONSTRUCT(class, virt_class, constructor, context, ...) \
    (class)(((virt_class) (&__ ## class))->constructor( \
        (virt_class) _talloc_memdup( \
            context, &__ ## class, \
            sizeof(struct class ## _t), \
            __location__ "(" #class ")"), \
        ## __VA_ARGS__) )

/* _talloc_memdup version
#define CONSTRUCT_CREATE(class, virt_class, context) \
     (virt_class) _talloc_memdup(context, &__ ## class, sizeof(struct class ## _t), __location__ "(" #class ")")
*/

#define CONSTRUCT_CREATE(class, virt_class, context) \
     (virt_class) talloc_memdup(context, &__ ## class, sizeof(struct class ## _t))

#define CONSTRUCT_INITIALIZE(class, virt_class, constructor, object, ...) \
    (class)(((virt_class) (&__ ## class))->constructor(object, ## __VA_ARGS__))

/* This variant is useful when all we have is a class reference
 *   (GETCLASS(Foo)) or &__Foo
 */
#define CONSTRUCT_FROM_REFERENCE(class, constructor, context, ... )	\
  ( (class)->constructor(						\
                       (void *)_talloc_memdup(context, ((Object)class), ((Object)class)->__size,  __location__ "(" #class "." #constructor ")"), \
		      ## __VA_ARGS__) )

/* Finds the size of the class in x */
#define CLASS_SIZE(class)			\
  ((Object)class)->__size

typedef struct Object_t *Object;

struct Object_t {
  //A reference to a class instance - this is useful to be able to
  //tell which class an object really belongs to:
  Object __class__;

  //And its super class:
  Object __super__;

  char *__name__;

  /** Objects may have a doc string associated with them. */
  char *__doc__;

  //How large the class is:
  int __size;

  /* A pointer to an extension - An extension is some other arbitrary
     object which may be linked with this one.
  */
  void *extension;
};

#define SUPER(base, imp, method, ...)            \
  ((base)&__ ## imp)->method((base)self, ## __VA_ARGS__)

#define GETCLASS(class)				\
  (Object)&__ ## class

// Returns true if the obj belongs to the class
#define ISINSTANCE(obj,class)			\
  (((Object)obj)->__class__ == GETCLASS(class))

// This is a string comparison version of ISINSTANCE which works
// across different shared objects.
#define ISNAMEINSTANCE(obj, class)		\
  (obj && !strcmp(class, NAMEOF(obj)))

// We need to ensure that class was properly initialised:
#define ISSUBCLASS(obj,class)			\
  issubclass((Object)obj, (Object)&__ ## class)

#define CLASSOF(obj)				\
  ((Object)obj)->__class__

DLL_PUBLIC PYTSK_INLINE void Object_init(Object);

DLL_PUBLIC extern struct Object_t __Object;

/** Find out if obj is an instance of cls or a derived class.

    Use like this:

    if(issubclass(obj, (Object)&__FileLikeObject)) {
       ...
    };


    You can also do this in a faster way if you already know the class
    hierarchy (but it could break if the hierarchy changes):
    {
     Object cls = ((Object)obj)->__class__;

     if(cls == (Object)&__Image || \
        cls == (Object)&__FileLikeObject || \
        cls == (Object)&__AFFObject || ....) {
     ...
     };
    };
 */
int issubclass(Object obj, Object class);

DLL_PUBLIC extern void unimplemented(Object self);

#define UNIMPLEMENTED(class, method)             \
  ((class)self)->method = (void *)unimplemented;

#define ZSTRING_NO_NULL(str) str , (strlen(str))
#define ZSTRING(str) str , (strlen(str)+1)

  // These dont do anything but are useful to indicate when a function
  // parameter is used purely to return a value. They are now used to
  // assist the python binding generator in generating the right sort
  // of code
#define OUT
#define IN

  // This modifier before a class means that the class is abstract and
  // does not have an implementation - we do not generate bindings for
  // that class then.
#define ABSTRACT

  // This modifier indicates that the following pointer is pointing to
  // a borrowed reference - callers must not free the memory after use.
#define BORROWED

  // This tells the autobinder to generated bindings to this struct
#define BOUND

  // This tells the autobinder to ignore this class as it should be
  // private to the implementation - external callers should not
  // access this.
#define PRIVATE

  // This attribute of a method means that this method is a
  // desctructor - the object is no longer valid after this method is
  // run
#define DESTRUCTOR

  // including this after an argument definition will cause the
  // autogenerator to assign default values to that parameter and make
  // it optional
#define DEFAULT(x)

  // This explicitely denote that the type is a null terminated char
  // ptr as opposed to a pointer to char and length.
typedef char * ZString;

  /* The following is a direction for the autogenerator to proxy the
     given class. This is done in the following way:

1) a new python type is created called Proxy_class_name() with a
constructor which takes a surrogate object.

2) The proxy class contains a member "base" of the type of the proxied
C class.

3) The returned python object may be passed to any C functions which
expect the proxied class, and internal C calls will be converted to
python method calls on the proxied object.
  */
#define PROXY_CLASS(name)

  /* This signals the autogenerator to bind the named struct */
#define BIND_STRUCT(name)

  // This means that the memory owned by this pointer is managed
  // externally (not using talloc). It is dangerous to use this
  // keyword too much because we are unable to manage its memory
  // appropriately and it can be free'd from under us.
#define FOREIGN

#endif
#ifdef __cplusplus
} /* closing brace for extern "C" */
#endif

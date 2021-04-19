/* SleuthKit functions.
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

#include "tsk3.h"

#include <time.h>

#if defined( TSK_MULTITHREAD_LIB )

extern "C" {
extern void tsk_init_lock(tsk_lock_t * lock);
extern void tsk_deinit_lock(tsk_lock_t * lock);
}

#endif /* defined( TSK_MULTITHREAD_LIB ) */

/* Prototypes for IMG_INFO hooks
 * Note that IMG_INFO_read is called by the SleuthKit the Img_Info_read
 * is its equivalent called by the pytsk3 when no proxy object is defined.
 */
ssize_t IMG_INFO_read(TSK_IMG_INFO *self, TSK_OFF_T off, char *buf, size_t len);
void IMG_INFO_close(TSK_IMG_INFO *self);

/* This macro is used to receive the object reference from a member of the type.
 */
#define GET_Object_from_member(type, object, member) \
    (type)(((char *)object) - (unsigned long)(&((type)0)->member))

/* Img_Info destructor
 */
static int Img_Info_dest(Img_Info self) {
    if(self == NULL) {
        return -1;
    }
    tsk_img_close((TSK_IMG_INFO *) self->img);

    if(self->img_is_internal != 0) {
#if defined( TSK_MULTITHREAD_LIB )
        tsk_deinit_lock(&(self->img->base.cache_lock));
#endif
        // If img is internal talloc will free it.
    }
    self->img = NULL;

    return 0;
}

/* Img_Info constructor
 */
static Img_Info Img_Info_Con(Img_Info self, char *urn, TSK_IMG_TYPE_ENUM type) {

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(urn != NULL && urn[0] != 0) {
#ifdef TSK_VERSION_NUM
        self->img = (Extended_TSK_IMG_INFO *) tsk_img_open_utf8(1, (const char **) &urn, type, 0);
#else
        self->img = (Extended_TSK_IMG_INFO *) tsk_img_open_utf8(1, (const char **) &urn, type);
#endif
        self->img_is_internal = 0;

    } else {
        // Initialise the img struct with the correct callbacks:
        self->img = talloc_zero(self, Extended_TSK_IMG_INFO);
        self->img_is_internal = 1;

        self->img->container = self;

#if defined( TSK_MULTITHREAD_LIB )
        tsk_init_lock(&(self->img->base.cache_lock));
#endif

        self->img->base.read = IMG_INFO_read;
        self->img->base.close = IMG_INFO_close;
        self->img->base.size = CALL(self, get_size);

#ifdef TSK_VERSION_NUM
        self->img->base.sector_size = 512;
#endif
#if defined( TSK_VERSION_NUM ) && ( TSK_VERSION_NUM >= 0x040103ff )
        self->img->base.itype = TSK_IMG_TYPE_EXTERNAL;
#else
        self->img->base.itype = TSK_IMG_TYPE_RAW_SING;
#endif
    }
    if(self->img == NULL) {
        RaiseError(EIOError, "Unable to open image: %s", tsk_error_get());
        tsk_error_reset();
        return NULL;
    }
    self->img_is_open = 1;

    talloc_set_destructor((void *) self, (int(*)(void *)) &Img_Info_dest);

    return self;
}

uint64_t Img_Info_read(Img_Info self, TSK_OFF_T off, OUT char *buf, size_t len) {
    ssize_t read_count = 0;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return 0;
    }
    if(self->img_is_open == 0) {
        RaiseError(EIOError, "Invalid Img_Info not opened.");
        return 0;
    }
    if(off < 0) {
        RaiseError(EIOError, "Invalid offset value out of bounds.");
        return 0;
    }
    if(buf == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: buf.");
        return 0;
    }
    read_count = CALL((TSK_IMG_INFO *) self->img, read, off, buf, len);

    if(read_count < 0) {
        RaiseError(EIOError, "Unable to read image: %s", tsk_error_get());
        tsk_error_reset();
        return 0;
    }
    return read_count;
}

void Img_Info_close(Img_Info self) {
    if(self != NULL) {
        self->img_is_open = 0;
    }
}

uint64_t Img_Info_get_size(Img_Info self) {
    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return 0;
    }
    if(self->img != NULL) {
        return ((TSK_IMG_INFO *) self->img)->size;
    }
    return (uint64_t) -1;
}

VIRTUAL(Img_Info, Object) {
    VMETHOD(Con) = Img_Info_Con;
    VMETHOD(read) = Img_Info_read;
    VMETHOD(close) = Img_Info_close;
    VMETHOD(get_size) = Img_Info_get_size;
} END_VIRTUAL

void IMG_INFO_close(TSK_IMG_INFO *img) {
    Extended_TSK_IMG_INFO *self = (Extended_TSK_IMG_INFO *) img;

    CALL(self->container, close);
};

ssize_t IMG_INFO_read(TSK_IMG_INFO *img, TSK_OFF_T off, char *buf, size_t len) {
    Extended_TSK_IMG_INFO *self = (Extended_TSK_IMG_INFO *) img;

    if(len == 0) {
      return 0;
    }
    return (ssize_t) CALL(self->container, read, (uint64_t) off, buf, len);
}

/* FS_Info destructor
 */
int FS_Info_dest(FS_Info self) {
    if(self == NULL) {
        return -1;
    }
    tsk_fs_close(self->info);

    self->info = NULL;
    self->extended_img_info = NULL;

    return 0;
}

/* FS_Info constructor
 */
static FS_Info FS_Info_Con(FS_Info self, Img_Info img, TSK_OFF_T offset,
                           TSK_FS_TYPE_ENUM type) {
    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(img == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: img.");
        return NULL;
    }
    self->extended_img_info = img->img;

    self->info = tsk_fs_open_img((TSK_IMG_INFO *) self->extended_img_info, offset, type);

    if(!self->info) {
        RaiseError(EIOError, "Unable to open the image as a filesystem at offset: 0x%08" PRIxOFF " with error: %s",
                   offset, tsk_error_get());
        tsk_error_reset();
        return NULL;
    }
    // Make sure that the filesystem is properly closed when we get freed
    talloc_set_destructor((void *) self, (int(*)(void *)) &FS_Info_dest);

    return self;
}

static Directory FS_Info_open_dir(FS_Info self, ZString path, TSK_INUM_T inode) {
    Directory object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(Directory, Directory, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(Directory, Directory, Con, object, self, path, inode) == NULL) {
            goto on_error;
        }
    }
    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    return NULL;
};

static File FS_Info_open(FS_Info self, ZString path) {
    TSK_FS_FILE *info = NULL;
    File object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    info = tsk_fs_file_open(self->info, NULL, path);

    if(info == NULL) {
        RaiseError(EIOError, "Unable to open file: %s", tsk_error_get());
        tsk_error_reset();
        goto on_error;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(File, File, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(File, File, Con, object, self, info) == NULL) {
            goto on_error;
        }
        // Tell the File object to manage info.
        object->info_is_internal = 1;
    }
    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    if(info != NULL) {
        tsk_fs_file_close(info);
    }
    return NULL;
};

static File FS_Info_open_meta(FS_Info self, TSK_INUM_T inode) {
    TSK_FS_FILE *info = NULL;
    File object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    info = tsk_fs_file_open_meta(self->info, NULL, inode);

    if(info == NULL) {
        RaiseError(EIOError, "Unable to open file: %s", tsk_error_get());
        tsk_error_reset();
        goto on_error;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(File, File, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(File, File, Con, object, self, info) == NULL) {
            goto on_error;
        }
        // Tell the File object to manage info.
        object->info_is_internal = 1;
    }
    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    if(info != NULL) {
        tsk_fs_file_close(info);
    }
    return NULL;
}

static void FS_Info_exit(FS_Info self PYTSK3_ATTRIBUTE_UNUSED) {
  PYTSK3_UNREFERENCED_PARAMETER(self)
  exit(0);
};

VIRTUAL(FS_Info, Object) {
  VMETHOD(Con) = FS_Info_Con;
  VMETHOD(open_dir) = FS_Info_open_dir;
  VMETHOD(open) = FS_Info_open;
  VMETHOD(open_meta) = FS_Info_open_meta;
  VMETHOD(exit) = FS_Info_exit;
} END_VIRTUAL

/* Directory destructor
 */
static int Directory_dest(Directory self) {
    if(self == NULL) {
        return -1;
    }
    tsk_fs_dir_close(self->info);
    self->info = NULL;

    return 0;
}

/* Directory constructor
 */
static Directory Directory_Con(Directory self, FS_Info fs, ZString path, TSK_INUM_T inode) {

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(fs == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: fs.");
        return NULL;
    }
    if(path == NULL) {
        self->info = tsk_fs_dir_open_meta(fs->info, inode);
    } else {
        self->info = tsk_fs_dir_open(fs->info, path);
    }
    if(self->info == NULL) {
        RaiseError(EIOError, "Unable to open directory: %s", tsk_error_get());
        tsk_error_reset();
        return NULL;
    }
    self->current = 0;
    self->size = tsk_fs_dir_getsize(self->info);
    self->fs = fs;

    // TODO: is this still applicable?
    // Add a reference to them to ensure they dont get freed until we do.
    // talloc_reference(self, fs);

    talloc_set_destructor((void *) self, (int(*)(void *)) &Directory_dest);

    return self;
}

static File Directory_next(Directory self) {
    TSK_FS_FILE *info = NULL;
    File object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if((self->current < 0) || ((uint64_t) self->current > (uint64_t) self->size)) {
        RaiseError(EInvalidParameter, "Invalid parameter: current.");
        return NULL;
    }
    if((uint64_t) self->current == (uint64_t) self->size) {
        return NULL;
    }
    info = tsk_fs_dir_get(self->info, self->current);

    if(info == NULL) {
        RaiseError(EIOError, "Error opening File: %s", tsk_error_get());
        tsk_error_reset();
        goto on_error;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(File, File, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(File, File, Con, object, self->fs, info) == NULL) {
            goto on_error;
        }
        // Tell the File object to manage info.
        object->info_is_internal = 1;
    }
    self->current++;

    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    if(info != NULL) {
        tsk_fs_file_close(info);
    }
    return NULL;
};

static void Directory_iter(Directory self) {
  self->current = 0;
};

VIRTUAL(Directory, Object) {
  VMETHOD(Con) = Directory_Con;
  VMETHOD(iternext) = Directory_next;
  VMETHOD(__iter__) = Directory_iter;
} END_VIRTUAL

/* File destructor
 */
static int File_dest(File self) {
    if(self == NULL) {
        return -1;
    }
    if(self->info_is_internal != 0) {
        // Here internal refers to the File object managing info
        // not that info was allocated by talloc.
        tsk_fs_file_close(self->info);
    }
    self->info = NULL;

    return 0;
}

/* File constructor
 */
static File File_Con(File self, FS_Info fs, TSK_FS_FILE *info) {
    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(fs == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: fs.");
        return NULL;
    }
    if(info == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: info.");
        return NULL;
    }
    self->fs = fs;
    self->info = info;

    // Get the total number of attributes.
    self->max_attr = tsk_fs_file_attr_getsize(info);

    talloc_set_destructor((void *) self, (int(*)(void *)) &File_dest);

    return self;
};

static uint64_t File_read_random(File self, TSK_OFF_T offset,
                                OUT char *buff, int len,
                                TSK_FS_ATTR_TYPE_ENUM type, int id,
                                TSK_FS_FILE_READ_FLAG_ENUM flags) {
  ssize_t result;

  if((id < -1) || (id > 0xffff)) {
    RaiseError(EInvalidParameter, "id parameter is invalid.");
    return 0;
  };
  if(id == -1) {
    result = tsk_fs_file_read(self->info, offset, buff, len, flags);
  } else {
    result = tsk_fs_file_read_type(self->info, type, (uint16_t) id, offset, buff, len, flags);
  };

  if(result < 0) {
    RaiseError(EIOError, "Read error: %s", tsk_error_get());
    tsk_error_reset();
    return 0;
  };

  return result;
};

static Directory File_as_directory(File self) {
    Directory object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(self->info == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self->info.");
        return NULL;
    }
#if defined( TSK_VERSION_NUM ) && ( TSK_VERSION_NUM >= 0x040402ff )
    if(self->info->meta == NULL || !(TSK_FS_IS_DIR_META(self->info->meta->type))) {
#else
    if(self->info->meta == NULL || self->info->meta->type != TSK_FS_META_TYPE_DIR) {
#endif
        RaiseError(EIOError, "Not a directory");
        return NULL;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(Directory, Directory, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(Directory, Directory, Con, object, self->fs, NULL, self->info->meta->addr) == NULL) {
            goto on_error;
        }
    }
    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    return NULL;
};

static Attribute File_iternext(File self) {
    TSK_FS_ATTR *attribute = NULL;
    Attribute object = NULL;

    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(self->current_attr < 0 || self->current_attr > self->max_attr) {
        RaiseError(EInvalidParameter, "Invalid parameter: self->current_attr.");
        return NULL;
    }
    if(self->current_attr == self->max_attr) {
        return NULL;
    }
    // It looks like attribute is managed by the SleuthKit.
    attribute = (TSK_FS_ATTR *) tsk_fs_file_attr_get_idx(self->info, self->current_attr);

    if(!attribute)  {
        RaiseError(EIOError, "Error opening File: %s", tsk_error_get());
        tsk_error_reset();
        return NULL;
    }
    // CONSTRUCT_CREATE calls _talloc_memdup to allocate memory for the object.
    object = CONSTRUCT_CREATE(Attribute, Attribute, NULL);

    if(object != NULL) {
        // CONSTRUCT_INITIALIZE calls the constructor function on the object.
        if(CONSTRUCT_INITIALIZE(Attribute, Attribute, Con, object, attribute) == NULL) {
            goto on_error;
        }
    }
    self->current_attr++;

    return object;

on_error:
    if(object != NULL) {
        talloc_free(object);
    }
    return NULL;
};

static void File_iter__(File self) {
  self->current_attr = 0;
};

VIRTUAL(File, Object) {
  VMETHOD(Con) = File_Con;
  VMETHOD(read_random) = File_read_random;
  VMETHOD(as_directory) = File_as_directory;
  VMETHOD(iternext) = File_iternext;
  VMETHOD(__iter__) = File_iter__;
} END_VIRTUAL

/* Attribute constructor
 */
static Attribute Attribute_Con(Attribute self, TSK_FS_ATTR *info) {
    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(info == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: info.");
        return NULL;
    }
    self->info = info;

    return self;
}

static void Attribute_iter(Attribute self) {
  self->current = self->info->nrd.run;
};

static TSK_FS_ATTR_RUN *Attribute_iternext(Attribute self) {
    TSK_FS_ATTR_RUN *result = NULL;

    if(self->current == NULL) {
        return NULL;
    }
    result = self->current;

    self->current = self->current->next;

    if(self->current == self->info->nrd.run) {
        self->current = NULL;
    }
    return (TSK_FS_ATTR_RUN *) talloc_memdup(NULL, result, sizeof(*result));
}

VIRTUAL(Attribute, Object) {
    VMETHOD(Con) = Attribute_Con;
    VMETHOD(iternext) = Attribute_iternext;
    VMETHOD(__iter__) = Attribute_iter;
} END_VIRTUAL

/* The following implement the volume system. */

/* Volume_Info destructor
 */
static int Volume_Info_dest(Volume_Info self) {
    if(self == NULL) {
        return -1;
    }
    tsk_vs_close(self->info);
    self->info = NULL;

    return 0;
}

/* Volume_Info constructor
 */
static Volume_Info Volume_Info_Con(Volume_Info self, Img_Info img,
                                   TSK_VS_TYPE_ENUM type,
                                   TSK_OFF_T offset) {
    if(self == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: self.");
        return NULL;
    }
    if(img == NULL) {
        RaiseError(EInvalidParameter, "Invalid parameter: img.");
        return NULL;
    }
    self->info = tsk_vs_open((TSK_IMG_INFO *) img->img, offset, type);

    if(self->info == NULL) {
        RaiseError(EIOError, "Error opening Volume_Info: %s", tsk_error_get());
        tsk_error_reset();
        return NULL;
    }
    talloc_set_destructor((void *) self, (int(*)(void *)) &Volume_Info_dest);

    return self;
}

static void Volume_Info_iter(Volume_Info self) {
  self->current = 0;
};

static TSK_VS_PART_INFO *Volume_Info_iternext(Volume_Info self) {
  return (TSK_VS_PART_INFO *)tsk_vs_part_get(self->info, self->current++);
};

VIRTUAL(Volume_Info, Object) {
  VMETHOD(Con) = Volume_Info_Con;
  VMETHOD(__iter__) = Volume_Info_iter;
  VMETHOD(iternext) = Volume_Info_iternext;
} END_VIRTUAL


void tsk_init() {

  // libtsk uses mktime and localtime that rely on the TZ environment variable
  // however that leads to inconsistent behavior with different TZ values.
  // Hence that we force TZ to be UTC, when possible.
#if defined( _MSC_VER )
  _putenv_s("TZ", "UTC");
  _tzset();

  // Some installations of MinGW do not support setenv
#elif !defined( __MINGW32__ )
  setenv("TZ", "UTC", 1);
  tzset();
#endif

  //tsk_verbose++;
  Img_Info_init((Object)&__Img_Info);
  FS_Info_init((Object)&__FS_Info);
  Directory_init((Object)&__Directory);
  File_init((Object)&__File);
  Attribute_init((Object)&__Attribute);
  Volume_Info_init((Object)&__Volume_Info);
};

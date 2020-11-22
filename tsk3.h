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
#if !defined( TSK3_H_ )
#define TSK3_H_

#if defined( HAVE_TSK3_LIBTSK_H )
#include <tsk3/libtsk.h>
#elif defined( HAVE_TSK_LIBTSK_H )
#include <tsk/libtsk.h>
#else
#error Missing libtsk header
#endif

#include "aff4_errors.h"
#include "class.h"

typedef struct {
  TSK_IMG_INFO base;
  struct Img_Info_t *container;
} Extended_TSK_IMG_INFO;

BIND_STRUCT(Extended_TSK_IMG_INFO);

/** Bind the following structs */
BIND_STRUCT(TSK_FS_INFO);
BIND_STRUCT(TSK_FS_NAME);
BIND_STRUCT(TSK_FS_META);
BIND_STRUCT(TSK_FS_DIR);
BIND_STRUCT(TSK_FS_FILE);
BIND_STRUCT(TSK_FS_BLOCK);
BIND_STRUCT(TSK_FS_ATTR);
BIND_STRUCT(TSK_FS_ATTR_RUN);
BIND_STRUCT(TSK_VS_PART_INFO);
BIND_STRUCT(TSK_VS_INFO);

/** This is a normal IMG_INFO which takes a filename and passes it
    to TSK. It just uses the standard TSK image handling code to
    support EWF, AFF etc.

    This is usually the first object you would instantiate in order to
    use the TSK library:

    img = Img_Info(filename)

    you would then pass it to an FS_Info object:

    fs = FS_Info(img)

    Then open an inode or path

    f = fs.open_dir(inode = 2)
*/
CCLASS(Img_Info, Object)
     PRIVATE Extended_TSK_IMG_INFO *img;

     /* Value to indicate if img is managed internally
      */
     PRIVATE int img_is_internal;

     /* Value to indicate if img is open 
      */
     PRIVATE int img_is_open;

     /* Open an image using the Sleuthkit.
      *
      * DEFAULT(type) = TSK_IMG_TYPE_DETECT;
      * DEFAULT(url) = "";
      */
     Img_Info METHOD(Img_Info, Con, ZString url, TSK_IMG_TYPE_ENUM type);

     /* Read a random buffer from the image */
     uint64_t METHOD(Img_Info, read, TSK_OFF_T off, OUT char *buf, size_t len);

     /* Retrieve the size of the image */
     uint64_t METHOD(Img_Info, get_size);

     /* Closes the image */
     void METHOD(Img_Info, close);
END_CCLASS

/** This object handles volumes.
 */
CCLASS(Volume_Info, Object)
  FOREIGN TSK_VS_INFO *info;
  int current;

  /** Open a volume using the Sleuthkit.

      DEFAULT(offset) = 0;
      DEFAULT(type) = TSK_VS_TYPE_DETECT;
  */
  Volume_Info METHOD(Volume_Info, Con, Img_Info img,
                     TSK_VS_TYPE_ENUM type, TSK_OFF_T offset);
  void METHOD(Volume_Info, __iter__);
  TSK_VS_PART_INFO *METHOD(Volume_Info, iternext);
END_CCLASS

// Forward declerations
struct FS_Info_t;
struct Directory_t;

/** An attribute is associated with a file. In some filesystem
    (e.g. NTFS) a file may contain many attributes.

    Attributes can be iterated over to obtain the attribute runs
    (e.g. to recover block allocation information).

*/
CCLASS(Attribute, Object)
   FOREIGN TSK_FS_ATTR *info;
   FOREIGN TSK_FS_ATTR_RUN *current;

   Attribute METHOD(Attribute, Con, TSK_FS_ATTR *info);

   void METHOD(Attribute, __iter__);
   TSK_FS_ATTR_RUN *METHOD(Attribute, iternext);
END_CCLASS


/** This represents a file object. A file has both metadata and
    data streams.

    Its usually not useful to instantiate this C class by itself -
    you need to call FS_Info.open() or iterate over a Directory()
    object.

    This object may be used to read the content of the file using
    read_random().

    Iterating over this object will return all the attributes for
    this file.
*/
CCLASS(File, Object)
     FOREIGN TSK_FS_FILE *info;

     /* Value to indicate if info is managed internally
      */
     PRIVATE int info_is_internal;

     PRIVATE struct FS_Info_t *fs;

     int max_attr;
     int current_attr;

     File METHOD(File, Con, struct FS_Info_t *fs, TSK_FS_FILE *info);

     /** Read a buffer from a random location in the file.

         DEFAULT(flags) = 0;
         DEFAULT(type) = TSK_FS_ATTR_TYPE_DEFAULT;
         DEFAULT(id) = -1;
     */
     uint64_t METHOD(File, read_random, TSK_OFF_T offset,
                    OUT char *buff, int len,
                    TSK_FS_ATTR_TYPE_ENUM type, int id,
                    TSK_FS_FILE_READ_FLAG_ENUM flags);

     /* Obtain a directory object that represents this inode. This may
        be useful if the file is actually a directory and we want to
        iterate over its contents.
      */
     struct Directory_t *METHOD(File, as_directory);

     void METHOD(File, __iter__);
     Attribute METHOD(File, iternext);
END_CCLASS

/** This represents a Directory within the filesystem. You can
    iterate over this object to obtain all the File objects
    contained within this directory:

    for f in d:
        print f.info.name.name
*/
CCLASS(Directory, Object)
     TSK_FS_DIR *info;
     PRIVATE struct FS_Info_t *fs;

     /* Total number of files in this directory */
     size_t size;

     /* Current file returned in the next iteration */
     int current;

     /* We can open the directory using a path, its inode number.

        DEFAULT(path) = NULL;
        DEFAULT(inode) = 0;
      */
     Directory METHOD(Directory, Con, struct FS_Info_t *fs, \
                      ZString path, TSK_INUM_T inode);

     /** An iterator of all files in the present directory. */
     void METHOD(Directory, __iter__);
     File METHOD(Directory, iternext);
END_CCLASS

/** This is used to obtain a filesystem object from an Img_Info object.

    From this FS_Info we can open files or directories by inode, or
    path.
 */
CCLASS(FS_Info, Object)
     FOREIGN TSK_FS_INFO *info;

     PRIVATE Extended_TSK_IMG_INFO *extended_img_info;

     /** Open the filesystem stored on image.

       DEFAULT(type) = TSK_FS_TYPE_DETECT;
       DEFAULT(offset) = 0;
     */
     FS_Info METHOD(FS_Info, Con, Img_Info img, TSK_OFF_T offset,
                    TSK_FS_TYPE_ENUM type);

     /** A convenience function to open a directory in this image.

         DEFAULT(path) = NULL;
         DEFAULT(inode) = 2;
     */
     Directory METHOD(FS_Info, open_dir, ZString path, TSK_INUM_T inode);

     /** A convenience function to open a file in this image. */
     File METHOD(FS_Info, open, ZString path);

     // Open a file by inode number
     File METHOD(FS_Info, open_meta, TSK_INUM_T inode);

     void METHOD(FS_Info, exit);

END_CCLASS

     int *tsk_get_current_error(char **buff);

void tsk_init(void);

#endif /* !TSK3_H_ */

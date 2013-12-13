#!/usr/bin/python
#
# Copyright 2011, Michael Cohen <scudette@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import images
import sys
import pytsk3
from optparse import OptionParser

parser = OptionParser()
parser.add_option("-f", "--fstype", default=None,
                  help="File system type (use '-f list' for supported types)")

parser.add_option("-o", "--offset", default=0, type="int",
                  help="Offset in the image (in bytes)")

parser.add_option("-t", "--type", default="raw",
                  help="Type of image. Currently supported options 'raw', "
                  "'ewf'")

(options, args) = parser.parse_args()


if not args:
  print "You must specify an image."
  sys.exit(-1)

img = images.SelectImage(options.type, args)

try:
  volume = pytsk3.Volume_Info(img)
  for part in volume:
    print part.addr, part.desc, "%ss(%s)" % (part.start, part.start * 512), part.len

except IOError, e:
  print ("Error %s: Maybe specify a different image type using "
         "the -t option?" % e)

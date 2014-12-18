#!/usr/bin/python
#
# Copyright 2013, Michael Cohen <scudette@gmail.com>.
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
"""A simple feed lexer."""

import re


class Lexer(object):
  """A generic feed lexer."""
  ## The following is a description of the states we have and the
  ## way we move through them: format is an array of
  ## [ state_re, re, token/action, next state ]
  tokens = []
  state = "INITIAL"
  buffer = ""
  error = 0
  verbose = 0
  state_stack = []
  processed = 0
  processed_buffer = ""
  saved_state = None
  flags = 0

  def __init__(self, verbose=0, fd=None):
    super(Lexer, self).__init__()
    self.encoding = "utf-8"

    if not self.verbose:
      self.verbose = verbose

    if len(self.tokens[0]) == 4:
      for row in self.tokens:
        row.append(re.compile(row[0], re.DOTALL))
        row.append(re.compile(row[1], re.DOTALL | re.M | re.S | self.flags))

    self.fd = fd

  def save_state(self, dummy_t=None, m=None):
    """Returns a dict which represents the current state of the lexer.

       When provided to restore_state, the lexer is guaranteed to be
       in the same state as when the save_state was called.

       Note that derived classes may need to extend this.
    """
    ## Unable to save our state if we have errors. We need to guarantee
    ## that we rewind to a good part of the file.
    if self.error:
      return
    try:
      end = m.end()
    except:
      end = 0

    self.saved_state = dict(
        state_stack = self.state_stack[:],
        processed = self.processed - end,
        processed_buffer = self.processed_buffer,
        readptr = self.fd.tell() - len(self.buffer) - end,
        state = self.state,
        objects = self.objects[:],
        error = self.error,
    )
    if self.verbose > 1:
      print("Saving state {0:s}".format(self.processed))

  def restore_state(self):
    state = self.saved_state
    if not state:
      return

    self.state_stack = state["state_stack"]
    self.processed = state["processed"]
    self.processed_buffer = state["processed_buffer"]
    self.buffer = ""
    self.fd.seek(state["readptr"])
    self.state = state["state"]
    self.objects = state["objects"]
    self.error = state["error"]

    if self.verbose > 1:
      print("Restoring state to offset {0:s}".format(self.processed))

  def next_token(self, end=True):
    ## Now try to match any of the regexes in order:
    current_state = self.state
    for _, re_str, token, next_state, state, regex in self.tokens:
      ## Does the rule apply for us now?
      if state.match(current_state):
        if self.verbose > 2:
          print("{0:s}: Trying to match {1:s} with {2:s}".format(
              self.state, repr(self.buffer[:10]), repr(re_str)))
        match = regex.match(self.buffer)
        if match:
          if self.verbose > 3:
            print("{0:s} matched {1:s}".format(
                re_str, match.group(0).encode("utf8")))

          ## The match consumes the data off the buffer (the
          ## handler can put it back if it likes)
          self.processed_buffer += self.buffer[:match.end()]
          self.buffer = self.buffer[match.end():]
          self.processed += match.end()

          ## Try to iterate over all the callbacks specified:
          for t in token.split(","):
            try:
              if self.verbose > 0:
                print("0x{0:X}: Calling {1:s} {2:s}".format(
                    self.processed, t, repr(match.group(0))))
              cb = getattr(self, t, self.default_handler)
            except AttributeError:
              continue

            ## Is there a callback to handle this action?
            callback_state = cb(t, match)
            if callback_state == "CONTINUE":
              continue

            elif callback_state:
              next_state = callback_state
              self.state = next_state

          if next_state:
            self.state = next_state

          return token

    ## Check that we are making progress - if we are too full, we
    ## assume we are stuck:
    if end and len(self.buffer) > 0 or len(self.buffer) > 1024:
      self.processed_buffer += self.buffer[:1]
      self.buffer = self.buffer[1:]
      self.ERROR(
          "Lexer Stuck, discarding 1 byte ({0:s}) - state {1:s}".format(
              repr(self.buffer[:10]), self.state))
      return "ERROR"

    ## No token were found
    return

  def feed(self, data):
    """Feeds the lexer.

    Args:
      data: binary string containing the data (instance of bytes).
    """
    self.buffer += data.decode(self.encoding)

  def empty(self):
    return not len(self.buffer)

  def default_handler(self, token, match):
    if self.verbose > 2:
      print("Default handler: {0:s} with {1:s}".format(
          token, repr(match.group(0))))

  def ERROR(self, message=None, weight=1):
    if self.verbose > 0 and message:
      print("Error({0:s}): {1:s}".format(weight, message))

    self.error += weight

  def PUSH_STATE(self, dummy_token=None, dummy_match=None):
    if self.verbose > 1:
      print("Storing state {0:s}".format(self.state))

    self.state_stack.append(self.state)

  def POP_STATE(self, dummy_token=None, dummy_match=None):
    try:
      state = self.state_stack.pop()
      if self.verbose > 1:
        print("Returned state to {0:s}".format(state))
    except IndexError:
      print("Tried to pop the state but failed - possible recursion error")
      state = None
    return state

  def close(self):
    """Just a conveniece function to force us to parse all the data."""
    while self.next_token():
      pass


class SelfFeederMixIn(Lexer):
  """This mixin is used to make a lexer which feeds itself one
     sector at the time.

     Note that self.fd must be the fd we read from.
  """
  def parse_fd(self, fd):
    self.feed(fd.read())
    while self.next_token():
      pass

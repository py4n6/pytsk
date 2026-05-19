#!/usr/bin/env python3
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

import os
import re
import sys

# This file does not follow the naming convention specified in .pylintrc.
# pylint: disable=invalid-name


class Lexer:
    """A generic lexer."""

    # The following is a description of the states we have and the way we move through
    # them: format is a list of ( state_re, re, token/action, next state ) which is
    # exended with 2 compiled regular expressions on initialization.
    _TOKENS = []

    def __init__(self, verbose=0, fd=None):
        """Initializes the lexer."""
        super().__init__()
        self.buffer = ""
        self.encoding = "utf-8"
        self.error = 0
        self.flags = 0
        self.objects = []
        self.processed = 0
        self.processed_buffer = ""
        self.saved_state = None
        self.state = "INITIAL"
        self.state_stack = []
        self.verbose = 0

        if not self.verbose:
            self.verbose = verbose

        if len(self._TOKENS[0]) == 4:
            for row in self._TOKENS:
                row.append(re.compile(row[0], re.DOTALL))
                row.append(re.compile(row[1], re.DOTALL | re.M | re.S | self.flags))

        self.file_object = fd

    def close(self):
        """Process the remaining tokens."""
        while self.next_token():
            pass

    def default_handler(self, token, match):
        """Default (or fallback) token handler."""
        if self.verbose > 2:
            match = repr(match.group(0))
            self.log(f"Default handler: {token:s} with {match:s}\n")

    def empty(self):
        """Check if the buffer is empty."""
        return not self.buffer

    def feed(self, data):
        """Add data to the the buffer.

        Args:
          data (bytes): data.
        """
        # TODO: catch decode exception.
        decoded_data = data.decode(self.encoding)
        self.buffer = "".join([self.buffer, decoded_data])

    def log(self, message):
        """Logs a message to stderr."""
        sys.stderr.write(f"{message:s}\n")

    def next_token(self, end=True):
        """Proceed to the next token."""
        # Now try to match any of the regexes in order.
        current_state = self.state
        for _, re_str, token, next_state, state, regex in self._TOKENS:
            # Does the rule apply for us now?
            if state.match(current_state):
                if self.verbose > 2:
                    data_in_buffer = repr(self.buffer[:10])
                    expression_string = repr(re_str)
                    self.log(
                        f"{self.state:s}: Trying to match {data_in_buffer:s}... with "
                        f"{expression_string:s}\n"
                    )

                match = regex.match(self.buffer)
                if match:
                    if self.verbose > 3:
                        data_in_buffer = repr(self.buffer[:10])
                        self.log(f"{re_str:s} matched {data_in_buffer:s}...\n")

                    # The match consumes the data off the buffer (the handler can put
                    # it back if it likes).
                    self.processed_buffer += self.buffer[: match.end()]
                    self.buffer = self.buffer[match.end() :]
                    self.processed += match.end()

                    # Try to iterate over all the callbacks specified:
                    for t in token.split(","):
                        try:
                            if self.verbose > 0:
                                data_in_buffer = repr(self.buffer[:10])
                                self.log(
                                    f"0x{self.processed:x}: Calling {t:s} "
                                    f"{data_in_buffer:s}...\n"
                                )
                            callback_method = getattr(self, t, self.default_handler)
                        except AttributeError:
                            continue

                        # Is there a callback to handle this action?
                        callback_state = callback_method(t, match)
                        if callback_state == "CONTINUE":
                            continue

                        if callback_state:
                            next_state = callback_state
                            self.state = next_state

                    if next_state:
                        self.state = next_state

                    return token

        # Check that we are making progress - if we are too full, we assume we are
        # stuck.
        if (end and self.buffer) or len(self.buffer) > 1024:
            self.processed_buffer += self.buffer[:1]
            self.buffer = self.buffer[1:]

            data_in_buffer = repr(self.buffer[:10])
            self.ERROR(
                f"Lexer Stuck, discarding 1 byte ({data_in_buffer:s}...) - state "
                f"{self.state:s}"
            )
            return "ERROR"

        # No token was found.
        return None

    def restore_state(self):
        """Restores the current state of the lexer."""
        state = self.saved_state
        if not state:
            return

        self.state_stack = state["state_stack"]
        self.processed = state["processed"]
        self.processed_buffer = state["processed_buffer"]
        self.buffer = ""
        self.file_object.seek(state["readptr"], os.SEEK_SET)
        self.state = state["state"]
        self.objects = state["objects"]
        self.error = state["error"]

        if self.verbose > 1:
            self.log(f"Restoring state to offset {self.processed:s}\n")

    def save_state(self, unused_token, match):
        """Saves (preserves) the current state of the lexer.

        When provided to restore_state, the lexer is guaranteed to be in the same state
        as when the save_state was called.
        """
        # Unable to save our state if we have errors. We need to guarantee that we
        # rewind to a good part of the file.
        if self.error:
            return

        try:
            end = match.end()
        finally:
            end = 0

        file_offset = self.file_object.tell() - len(self.buffer) - end

        self.saved_state = {
            "error": self.error,
            "objects": self.objects[:],
            "processed_buffer": self.processed_buffer,
            "processed": self.processed - end,
            "readptr": file_offset,
            "state": self.state,
            "state_stack": self.state_stack[:],
        }
        if self.verbose > 1:
            self.log(f"Saving state {self.processed:s}\n")

    # The following methods are state handlers that have a calling convention.
    # pylint: disable=invalid-name,unused-argument

    def ERROR(self, message, weight=1):
        """Handle an error (ERROR state)."""
        if self.verbose > 0 and message:
            self.log(f"Error({weight:d}): {message!s}\n")

        self.error += weight

    def POP_STATE(self, unused_token, unused_match):
        """Handle a POP_STATE state."""
        try:
            state = self.state_stack.pop()
            if self.verbose > 1:
                self.log(f"Returned state to {state:s}\n")
        except IndexError:
            self.log("Tried to pop the state but failed - possible recursion error\n")
            state = None
        return state

    def PUSH_STATE(self, unused_token, unused_match):
        """Handle a PUSH_STATE state."""
        if self.verbose > 1:
            self.log(f"Storing state {self.state:s}\n")

        self.state_stack.append(self.state)


class SelfFeederMixIn(Lexer):
    """Lexer that feeds itself from a file-like object."""

    def parse_fd(self, file_object):
        """Parse a file-like object."""
        self.feed(file_object.read())

        while self.next_token():
            pass

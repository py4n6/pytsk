#!/usr/bin/env python
# ******************************************************
# Michael Cohen <scudette@users.sourceforge.net>
#
# ******************************************************
#  Version: FLAG $Version: 0.87-pre1 Date: Thu Jun 12 00:48:38 EST 2008$
# ******************************************************
#
# * This program is free software; you can redistribute it and/or
# * modify it under the terms of the GNU General Public License
# * as published by the Free Software Foundation; either version 2
# * of the License, or (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
# ******************************************************
""" A simple feed lexer.
"""

import re,sys

class Lexer:
    """ A generic feed lexer """
    ## The following is a description of the states we have and the
    ## way we move through them: format is an array of
    ## [ state_re, re, token/action, next state ]
    tokens = []
    state = "INITIAL"
    buffer = ''
    error = 0
    verbose = 0
    state_stack = []
    processed = 0
    processed_buffer = ''
    saved_state = None
    flags = 0
    
    def __init__(self, verbose=0, fd=None):
        if not self.verbose:
            self.verbose = verbose

        if len(self.tokens[0])==4:
            for row in self.tokens:
                row.append(re.compile(row[0], re.DOTALL))
                row.append(re.compile(row[1], re.DOTALL | re.M | re.S | self.flags ))
                
        self.fd = fd

    def save_state(self, t=None, m=None):
        """ Returns a dict which represents the current state of the lexer.

        When provided to restore_state, the lexer is guaranteed to be
        in the same state as when the save_state was called.

        Note that derived classes may need to extend this.
        """
        ## Cant save our state if we have errors. We need to guarantee
        ## that we rewind to a good part of the file.
        if self.error: return
        try:
            end = m.end()
        except: end = 0
        
        self.saved_state = dict(state_stack = self.state_stack[:],
                                processed = self.processed - end,
                                processed_buffer = self.processed_buffer,
                                readptr = self.fd.tell() - len(self.buffer) - end,
                                state = self.state,
                                objects = self.objects[:],
                                error = self.error,
                                )

        if self.verbose>1:
            print "Saving state %s" % self.processed

    def restore_state(self):
        state = self.saved_state
        if not state: return
        
        self.state_stack = state['state_stack']
        self.processed = state['processed']
        self.processed_buffer = state['processed_buffer']
        self.buffer = ''
        self.fd.seek(state['readptr'])
        self.state = state['state']
        self.objects = state['objects']
        self.error = state['error']
        if self.verbose>1:
            print "Restoring state to offset %s" % self.processed

    def next_token(self, end = True):
        ## Now try to match any of the regexes in order:
        current_state = self.state
        for state_re, re_str, token, next, state, regex in self.tokens:
            ## Does the rule apply for us now?
            if state.match(current_state):
                if self.verbose > 2:
                    print "%s: Trying to match %r with %r" % (self.state, self.buffer[:10], re_str)
                m = regex.match(self.buffer)
                if m:
                    if self.verbose > 3:
                        print "%s matched %s" % (re_str, m.group(0).encode("utf8"))
                    ## The match consumes the data off the buffer (the
                    ## handler can put it back if it likes)
                    self.processed_buffer += self.buffer[:m.end()]
                    self.buffer = self.buffer[m.end():]
                    self.processed += m.end()

                    ## Try to iterate over all the callbacks specified:
                    for t in token.split(','):
                        try:
                            if self.verbose > 0:
                                print "0x%X: Calling %s %r" % (self.processed, t, m.group(0))
                            cb = getattr(self, t, self.default_handler)
                        except AttributeError:
                            continue

                        ## Is there a callback to handle this action?
                        next_state = cb(t, m)
                        if next_state == "CONTINUE":
                            continue

                        elif next_state:
                            next = next_state
                            self.state = next

                    
                    if next:
                        self.state = next
                
                    return token

        ## Check that we are making progress - if we are too full, we
        ## assume we are stuck:
        if end and len(self.buffer)>0 or len(self.buffer)>1024:
            self.processed_buffer += self.buffer[:1]
            self.buffer = self.buffer[1:]
            self.ERROR("Lexer Stuck, discarding 1 byte (%r) - state %s" % (self.buffer[:10], self.state))
            return "ERROR"

        ## No token were found
        return None
    
    def feed(self, data):
        self.buffer += data

    def empty(self):
        return not len(self.buffer)

    def default_handler(self, token, match):
        if self.verbose > 2:
            print "Default handler: %s with %r" % (token,match.group(0))

    def ERROR(self, message = None, weight =1):
        if self.verbose > 0 and message:
            print "Error(%s): %s" % (weight,message)

        self.error += weight

    def PUSH_STATE(self, token = None, match = None):
        if self.verbose > 1:
            print "Storing state %s" % self.state
        self.state_stack.append(self.state)

    def POP_STATE(self, token = None, match = None):
        try:
            state = self.state_stack.pop()
            if self.verbose > 1:
                print "Returned state to %s" % state
                
            return state
        except IndexError:
            print "Tried to pop the state but failed - possible recursion error"
            return None

    def close(self):
        """ Just a conveniece function to force us to parse all the data """
        while self.next_token(): pass

class SelfFeederMixIn(Lexer):
    """ This mixin is used to make a lexer which feeds itself one
    sector at the time.

    Note that self.fd must be the fd we read from.
    """
    def parse_fd(self, fd):
        self.feed(fd.read())
        while self.next_token(): pass


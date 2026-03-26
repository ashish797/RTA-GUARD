# Makefile for libdiscus — C bindings for RTA-GUARD Discus

CC      ?= gcc
CFLAGS  ?= -Wall -Wextra -O2 -std=c11
LDFLAGS ?=

LIB_NAME  = libdiscus
SRC       = discus.c
HEADER    = discus.h
OBJ       = discus.o
TEST_SRC  = test_discus.c
TEST_BIN  = test_discus

.PHONY: all lib test clean install uninstall

all: lib test

# Build static library
lib: $(OBJ)
	ar rcs $(LIB_NAME).a $(OBJ)
	@echo "Built $(LIB_NAME).a"

# Compile object
$(OBJ): $(SRC) $(HEADER)
	$(CC) $(CFLAGS) -c $(SRC) -o $(OBJ)

# Build and run tests
test: $(TEST_BIN)
	./$(TEST_BIN)
	@echo "All C binding tests passed"

$(TEST_BIN): $(TEST_SRC) $(SRC) $(HEADER)
	$(CC) $(CFLAGS) $(LDFLAGS) $(TEST_SRC) $(SRC) -o $(TEST_BIN)

# Install (system-wide)
install: lib
	install -d /usr/local/include/discus
	install -m 644 $(HEADER) /usr/local/include/discus/
	install -m 644 $(LIB_NAME).a /usr/local/lib/
	@echo "Installed to /usr/local/"

# Uninstall
uninstall:
	rm -f /usr/local/include/discus/$(HEADER)
	rm -f /usr/local/lib/$(LIB_NAME).a
	rmdir /usr/local/include/discus 2>/dev/null || true
	@echo "Uninstalled"

clean:
	rm -f $(OBJ) $(LIB_NAME).a $(TEST_BIN)

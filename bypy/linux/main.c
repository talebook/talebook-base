#include "util.h"

#include <stdio.h>
#include <stdlib.h>

#ifndef STANDALONE_CONVERTER
#define STANDALONE_CONVERTER 0
#endif

int
main(int argc, char **argv) {
    if (STANDALONE_CONVERTER) {
        if (setenv("CALIBRE_STANDALONE_CONVERTER", "1", 1) != 0) {
            fprintf(stderr, "Failed to set CALIBRE_STANDALONE_CONVERTER\n");
            return 1;
        }
    }
	execute_python_entrypoint(argc, argv, BASENAME, MODULE, FUNCTION, GUI_APP);
    return 0;
}

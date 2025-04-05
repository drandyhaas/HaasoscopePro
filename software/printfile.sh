hexdump -n 2560 -v -e '/1 " %u \n"' "$1" | awk '{printf "%d %s\n", NR-1, $0}'

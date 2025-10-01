#!/bin/bash
CERTDIR="/path/to/certs"

for cert in "$CERTDIR"/*.pem; do
    # Ignore empty files
    if [ -s "$cert" ]; then
        exp=$(openssl x509 -in "$cert" -noout -enddate 2>/dev/null | cut -d= -f2)
        if [ -n "$exp" ]; then
            usage="Unknown"
            case "$cert" in
                *1st-cert.pem*)            usage="1sr-cert Server" ;;
                *2nd-cert.pem*)            usage="2nd Certificate" ;;
                *) ;;
            esac
            printf "%s|%s|%s\n" "$(basename "$cert")" "$usage" "$exp"
        fi
    fi
done

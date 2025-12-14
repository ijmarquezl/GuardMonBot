#!/bin/bash
set -e

KEY_PATH="$HOME/.ssh/id_rsa"

echo "🔑 SSH Key Setup for GuardMonBot"

if [ -f "$KEY_PATH" ]; then
    echo "✅ Key already exists at: $KEY_PATH"
else
    echo "⚠️ No key found. Generating new RSA 4096 bit key..."
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    # Generate key non-interactively, no passphrase
    ssh-keygen -t rsa -b 4096 -f "$KEY_PATH" -N "" -C "guardmonbot-agent"
    echo "✅ Key generated!"
fi

echo ""
echo "📜 Your Public Key is:"
echo "--------------------------------------------------------"
cat "${KEY_PATH}.pub"
echo "--------------------------------------------------------"
echo ""
echo "🚀 NEXT STEPS:"
echo "To allow the bot to access a remote server, execute this command:"
echo "ssh-copy-id -i $KEY_PATH user@remote-ip"

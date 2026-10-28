const { makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

const authDir = path.resolve(__dirname, '../../auth_info_baileys');

if (!fs.existsSync(authDir) || !fs.existsSync(path.join(authDir, 'creds.json'))) {
    console.log("STATUS:NO_SESSION");
    process.exit(0);
}

async function probeSession() {
    const { state } = await useMultiFileAuthState(authDir);
    const sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false
    });

    const timer = setTimeout(() => {
        sock.end(undefined);
        console.log("STATUS:NO_SESSION");
        process.exit(0);
    }, 4000);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect } = update;

        if (connection === 'close') {
            clearTimeout(timer);
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
                // Borrar sesión rota
                try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (e) {}
                console.log("STATUS:NO_SESSION");
            } else {
                console.log("STATUS:NO_SESSION");
            }
            process.exit(0);
        } else if (connection === 'open') {
            clearTimeout(timer);
            console.log("STATUS:ACTIVE");
            sock.end(undefined);
            process.exit(0);
        }
    });
}

probeSession();

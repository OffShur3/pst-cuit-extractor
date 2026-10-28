const { makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const pino = require('pino');
const QRCode = require('qrcode');
const path = require('path');
const fs = require('fs');

const authDir = path.resolve(__dirname, '../../auth_info_baileys');
const dataDir = path.resolve(__dirname, '../../data');
const qrImagePath = path.join(dataDir, 'whatsapp_qr.png');

if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
}

async function iniciarSesion() {
    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    const sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        // Generar imagen PNG del código QR
        if (qr) {
            try {
                await QRCode.toFile(qrImagePath, qr, {
                    width: 320,
                    margin: 1,
                    color: { dark: '#000000', light: '#FFFFFF' }
                });
                console.log("EVENT:QR_GENERATED");
            } catch (err) {
                console.error("Error al generar imagen QR:", err);
            }
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            
            // Si la sesión expiró o fue deslogueada, borrar archivos y reiniciar inmediatamente
            if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
                console.log("EVENT:SESSION_EXPIRED");
                try {
                    fs.rmSync(authDir, { recursive: true, force: true });
                } catch (e) {}
                iniciarSesion();
            } else {
                iniciarSesion();
            }
        } else if (connection === 'open') {
            const phone = sock.user ? sock.user.id.split(':')[0] : 'OK';
            console.log(`EVENT:CONNECTED:+${phone}`);
            // Limpiar la imagen del QR para que no quede residuo
            if (fs.existsSync(qrImagePath)) {
                try { fs.unlinkSync(qrImagePath); } catch (e) {}
            }
            setTimeout(() => process.exit(0), 1000);
        }
    });
}

iniciarSesion();

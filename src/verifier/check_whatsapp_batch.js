const { makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

const authDir = path.resolve(__dirname, '../../auth_info_baileys');

async function verificarLote(numeros) {
    if (!numeros || numeros.length === 0) {
        process.stdout.write(JSON.stringify({}));
        process.exit(0);
    }

    if (!fs.existsSync(authDir)) {
        process.stderr.write("ERROR: No existe la carpeta auth_info_baileys. Ejecuta 'node src/verifier/login_whatsapp.js' primero.\n");
        process.exit(1);
    }

    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    const sock = makeWASocket({
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false
    });

    sock.ev.on('creds.update', saveCreds);

    // Timeout de seguridad por si no conecta
    const timer = setTimeout(() => {
        process.stderr.write("ERROR: Timeout esperando conexión con WhatsApp.\n");
        process.exit(1);
    }, 15000);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect } = update;

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            if (statusCode === DisconnectReason.loggedOut) {
                process.stderr.write("ERROR: Sesión cerrada en WhatsApp.\n");
                clearTimeout(timer);
                process.exit(1);
            }
        } else if (connection === 'open') {
            clearTimeout(timer);
            const resultadosMap = {};

            const jids = numeros.map(num => {
                const clean = num.replace(/\D/g, '');
                return `${clean}@s.whatsapp.net`;
            });

            try {
                const res = await sock.onWhatsApp(...jids);
                const existentesSet = new Set();
                
                if (res && res.length > 0) {
                    for (const r of res) {
                        if (r.exists) {
                            const numLimpio = r.jid.split('@')[0];
                            existentesSet.add(numLimpio);
                        }
                    }
                }

                for (const num of numeros) {
                    const clean = num.replace(/\D/g, '');
                    resultadosMap[clean] = existentesSet.has(clean);
                }

                process.stdout.write(JSON.stringify(resultadosMap));
            } catch (err) {
                process.stderr.write("Error en query Baileys: " + err.message + "\n");
            } finally {
                await sock.end(undefined);
                process.exit(0);
            }
        }
    });
}

const args = process.argv.slice(2);
if (args.length > 0) {
    if (args[0].endsWith('.json') && fs.existsSync(args[0])) {
        const lista = JSON.parse(fs.readFileSync(args[0], 'utf-8'));
        verificarLote(lista);
    } else {
        verificarLote(args);
    }
} else {
    process.stdout.write(JSON.stringify({}));
    process.exit(0);
}

// Local fixture based on the observed Palena wizard, with synthetic identities.
// No authentication, certificate, or CAF signing keys are used.
const http = require('node:http');
const counts = { refresh: 0, confirmation: 0, generation: 0, rejected: 0 };
const company = `<form method="post" action="/cvc_cgi/dte/of_solicita_folios_dcto">
  <input name="RUT_EMP"><input name="DV_EMP">
  <input name="ACEPTAR" type="submit" value="Continuar">
  <input name="NEW" type="button" value="Salir"></form>`;
const selection = `<form method="post" action="/cvc_cgi/dte/of_confirma_folio">
  <input name="RUT_EMP" value="76123456"><input name="DV_EMP" value="0">
  <select name="COD_DOCTO" onchange="changeRegregion('/cvc_cgi/dte/');">
    <option selected value="-1">NINGUNO</option><option selected value="33">FACTURA</option>
  </select><input name="MAX_AUTOR" readonly value="13">
  <input name="FOLIOS_DISP" readonly value="10"><input name="CANT_DOCTOS">
  <input name="ACEPTAR" type="submit" value="Solicitar Numeración">
  <input name="NEW" type="button" value="Volver"></form>`;
const confirmation = `<form method="post" action="/cvc_cgi/dte/of_genera_folio">
  <input name="COD_DOCTO" value="33"><input name="CANT_DOCTOS" value="1">
  <input name="NOMUSU" value="Persona Muñoz">
  <input name="ACEPTAR" type="submit" value="Obtener Folios"></form>`;

http.createServer((req, res) => {
  const chunks = [];
  req.on('data', chunk => chunks.push(chunk));
  req.on('end', () => {
    const body = Buffer.concat(chunks).toString('ascii');
    const fields = new URLSearchParams(body);
    const send = (status, text) => {
      res.writeHead(status, { 'Content-Type': 'text/html; charset=ISO-8859-1' });
      res.end(Buffer.from(text, 'latin1'));
    };
    const reject = () => {
      counts.rejected++;
      send(422, '<p>Transaccion rechazada: unexpected form payload</p>');
    };
    if (req.url === '/verification') return send(200, JSON.stringify(counts));
    if (req.method === 'GET' && req.url === '/cvc_cgi/dte/of_solicita_folios') return send(200, company);
    if (req.method !== 'POST') return send(501, 'Unmodeled request');
    if (fields.has('NEW')) return reject();
    if (req.url === '/cvc_cgi/dte/of_solicita_folios_dcto') {
      if (fields.has('COD_DOCTO')) {
        if (fields.has('ACEPTAR') || fields.get('COD_DOCTO') !== '33' || fields.get('CANT_DOCTOS') !== '') return reject();
        counts.refresh++;
      }
      return send(200, selection);
    }
    if (req.url === '/cvc_cgi/dte/of_confirma_folio') {
      if (!body.includes('ACEPTAR=Solicitar+Numeraci%F3n') || fields.get('CANT_DOCTOS') !== '1') return reject();
      counts.confirmation++;
      return send(200, confirmation);
    }
    if (req.url === '/cvc_cgi/dte/of_genera_folio') {
      if (!body.includes('NOMUSU=Persona+Mu%F1oz') || fields.get('CANT_DOCTOS') !== '1') return reject();
      counts.generation++;
      return send(200, '<AUTORIZACION><CAF><DA><TD>33</TD><RNG><D>1</D><H>1</H></RNG></DA></CAF></AUTORIZACION>');
    }
    send(501, 'Unmodeled request');
  });
}).listen(process.env.PORT);

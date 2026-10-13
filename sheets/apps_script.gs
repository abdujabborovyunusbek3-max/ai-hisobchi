/**
 * AI hisobchi -> Google Sheets.
 * O'rnatish: jadvalda Kengaytmalar (Extensions) -> Apps Script, shu kodni joylang,
 * SECRET ni o'zgartiring va Deploy -> New deployment -> Web app qiling
 * (Execute as: Me, Who has access: Anyone). README'da batafsil.
 */
const SECRET = 'BU_YERGA_MAXFIY_SOZ_YOZING';
const SHEET = 'Hisob';
const SUMMARY = 'Jami';
const HEADERS = ['ID', 'Sana', 'Turi', 'Summa', 'Valyuta', 'Kategoriya', 'Kim', 'Izoh', 'Manba'];

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SECRET) return reply_({ ok: false, error: 'secret' });
    const sheet = setup_();
    if (body.action === 'add') appendRows_(sheet, body.rows);
    else if (body.action === 'delete') deleteIds_(sheet, body.ids);
    else if (body.action === 'replace_all') {
      if (sheet.getLastRow() > 1) sheet.getRange(2, 1, sheet.getLastRow() - 1, HEADERS.length).clearContent();
      appendRows_(sheet, body.rows);
      compact_(sheet);
    } else return reply_({ ok: false, error: 'action' });
    return reply_({ ok: true });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function appendRows_(sheet, rows) {
  if (!rows || !rows.length) return;
  const values = rows.map(r => [r.id, r.date, r.type, r.amount, r.currency, r.category, r.person, r.note, r.source]);
  sheet.getRange(sheet.getLastRow() + 1, 1, values.length, HEADERS.length).setValues(values);
}

function deleteIds_(sheet, ids) {
  const last = sheet.getLastRow();
  if (last < 2) return;
  const col = sheet.getRange(2, 1, last - 1, 1).getValues();
  const wanted = new Set(ids.map(Number));
  for (let i = col.length - 1; i >= 0; i--) {
    if (wanted.has(Number(col[i][0]))) sheet.deleteRow(i + 2);
  }
}

function compact_(sheet) {
  // replace_all dan keyin bo'sh qolgan qatorlarni olib tashlash
  const max = sheet.getMaxRows(), last = Math.max(sheet.getLastRow(), 2);
  if (max > last + 50) sheet.deleteRows(last + 51, max - last - 50);
}

function setup_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET, 0);
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold').setBackground('#e8f0fe');
    sheet.setFrozenRows(1);
    sheet.getRange('B:B').setNumberFormat('yyyy-mm-dd');
    sheet.getRange('D:D').setNumberFormat('#,##0');
    sheet.setColumnWidths(1, HEADERS.length, 110);
  }
  if (!ss.getSheetByName(SUMMARY)) {
    const s = ss.insertSheet(SUMMARY, 1);
    s.getRange('A1').setValue('Umumiy (so\'m)').setFontWeight('bold');
    s.getRange('A2:B4').setValues([
      ['Kirim', `=SUMIFS(${SHEET}!D:D,${SHEET}!D:D,">0",${SHEET}!E:E,"UZS")`],
      ['Chiqim', `=-SUMIFS(${SHEET}!D:D,${SHEET}!D:D,"<0",${SHEET}!E:E,"UZS")`],
      ['Qoldiq', '=B2-B3'],
    ]);
    s.getRange('A6').setValue('Oylar va kategoriyalar bo\'yicha').setFontWeight('bold');
    s.getRange('A7').setFormula(
      `=IFERROR(QUERY(${SHEET}!A:I,"select Col6, sum(Col4) where Col5='UZS' and Col1 is not null ` +
      `group by Col6 pivot year(Col2)*100+month(Col2)+1 label sum(Col4) ''",1),"Hali yozuv yo'q")`);
    s.getRange('A2:Z200').setNumberFormat('#,##0');
  }
  return sheet;
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

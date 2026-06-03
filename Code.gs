function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('US Lead Pipeline Flow')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

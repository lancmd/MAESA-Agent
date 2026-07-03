/*****************************************
全国矿区 Sentinel-2 月尺度 NDWI / MNDWI 下载
适用于沉陷积水和水体季节变化监测
数据源：COPERNICUS/S2_SR_HARMONIZED
******************************************/

var roiAsset = 'users/your_username/your_mining_area';
var year = 2025;
var startMonth = 1;
var endMonth = 12;
var cloudPercent = 40;
var exportFolder = 'Mining_Monthly_Water_Index';
var exportCrs = null;
var noDataValue = -9999;

if (year < 2017) {
  throw new Error('Sentinel-2 L2A Harmonized 数据从 2017 年开始提供。');
}
if (startMonth < 1 || endMonth > 12 || startMonth > endMonth) {
  throw new Error('月份范围必须满足 1 <= startMonth <= endMonth <= 12。');
}

var roi = ee.FeatureCollection(roiAsset);
Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

function maskAndPrepareS2(image) {
  var scl = image.select('SCL');
  var mask = scl.neq(0)
    .and(scl.neq(1))
    .and(scl.neq(3))
    .and(scl.neq(8))
    .and(scl.neq(9))
    .and(scl.neq(10))
    .and(scl.neq(11));

  return image
    .select(['B3', 'B8', 'B11'], ['Green', 'NIR', 'SWIR1'])
    .multiply(0.0001)
    .updateMask(mask)
    .copyProperties(image, image.propertyNames());
}

function normalizedDifferenceSafe(input, firstBand, secondBand, outputName) {
  var denominator = input.select(firstBand).add(input.select(secondBand));
  return input.expression(
    '(a - b) / (a + b)',
    {
      a: input.select(firstBand),
      b: input.select(secondBand)
    }
  )
    .updateMask(denominator.neq(0))
    .rename(outputName);
}

var emptyImage = ee.Image.constant([0, 0, 0])
  .rename(['Green', 'NIR', 'SWIR1'])
  .updateMask(ee.Image(0));

for (var month = startMonth; month <= endMonth; month++) {
  var startDate = ee.Date.fromYMD(year, month, 1);
  var endDate = startDate.advance(1, 'month');
  var monthString = month < 10 ? '0' + month : String(month);

  var collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(roi)
    .filterDate(startDate, endDate)
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloudPercent))
    .map(maskAndPrepareS2);

  var imageCount = collection.size();
  print('Month ' + monthString + ' image count:', imageCount);

  // 无影像月份使用全掩膜占位影像，避免 median 后缺失波段导致脚本终止。
  var monthlyImage = ee.Image(ee.Algorithms.If(
    imageCount.gt(0),
    collection.median(),
    emptyImage
  )).clip(roi);

  var ndwi = normalizedDifferenceSafe(monthlyImage, 'Green', 'NIR', 'NDWI');
  var mndwi = normalizedDifferenceSafe(monthlyImage, 'Green', 'SWIR1', 'MNDWI');
  var waterIndex = ndwi.addBands(mndwi).toFloat();

  Map.addLayer(
    ndwi,
    {min: -1, max: 1, palette: ['brown', 'white', 'blue']},
    'NDWI_' + year + '_' + monthString,
    false
  );

  var exportName = 'Mining_Water_Index_' + year + '_' + monthString;
  var exportOptions = {
    image: waterIndex.unmask({value: noDataValue, sameFootprint: false}),
    description: exportName,
    fileNamePrefix: exportName,
    folder: exportFolder,
    region: roi.geometry(),
    scale: 10,
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true, noData: noDataValue}
  };

  if (exportCrs) {
    exportOptions.crs = exportCrs;
  }

  Export.image.toDrive(exportOptions);
}

/*****************************************
全国矿区 Sentinel-2 土地利用分类输入影像
适用年份：2017 年至今（2017—2018 年部分地区覆盖可能不完整）
数据源：COPERNICUS/S2_SR_HARMONIZED
输出：Blue、Green、Red、NIR、SWIR1、SWIR2、NDVI、NDWI、MNDWI、NDBI
******************************************/

// ===============================
// 1. 用户参数
// ===============================

var roiAsset = 'users/your_username/your_mining_area';
var year = 2025;
var startMonth = 6;
var endMonth = 10;
var cloudPercent = 30;
var exportFolder = 'Mining_LULC_Sentinel2';
var exportCrs = null;
var noDataValue = -9999;

if (year < 2017) {
  throw new Error('Sentinel-2 L2A Harmonized 数据从 2017 年开始提供。');
}
if (startMonth < 1 || endMonth > 12 || startMonth > endMonth) {
  throw new Error('月份范围必须满足 1 <= startMonth <= endMonth <= 12。');
}

var roi = ee.FeatureCollection(roiAsset);
var startDate = ee.Date.fromYMD(year, startMonth, 1);
var endDate = ee.Date.fromYMD(year, endMonth, 1).advance(1, 'month');

Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

// ===============================
// 2. SCL 去云与反射率缩放
// ===============================

function maskAndPrepareS2(image) {
  var scl = image.select('SCL');
  var mask = scl.neq(0)   // No Data
    .and(scl.neq(1))      // Saturated or defective
    .and(scl.neq(3))      // Cloud shadow
    .and(scl.neq(8))      // Cloud medium probability
    .and(scl.neq(9))      // Cloud high probability
    .and(scl.neq(10))     // Cirrus
    .and(scl.neq(11));    // Snow / ice

  // B11、B12 原始分辨率为 20 m，导出到 10 m 时由 Earth Engine 重采样。
  return image
    .select(
      ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'],
      ['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2']
    )
    .multiply(0.0001)
    .updateMask(mask)
    .copyProperties(image, image.propertyNames());
}

var collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi)
  .filterDate(startDate, endDate)
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloudPercent))
  .map(maskAndPrepareS2);

var imageCount = collection.size();
print('Date range:', startDate, endDate);
print('Sentinel-2 image count:', imageCount);

var emptyImage = ee.Image.constant([0, 0, 0, 0, 0, 0])
  .rename(['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2'])
  .updateMask(ee.Image(0));

var image = ee.Image(ee.Algorithms.If(
  imageCount.gt(0),
  collection.median(),
  emptyImage
)).clip(roi);

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

var ndvi = normalizedDifferenceSafe(image, 'NIR', 'Red', 'NDVI');
var ndwi = normalizedDifferenceSafe(image, 'Green', 'NIR', 'NDWI');
var mndwi = normalizedDifferenceSafe(image, 'Green', 'SWIR1', 'MNDWI');
var ndbi = normalizedDifferenceSafe(image, 'SWIR1', 'NIR', 'NDBI');

var classifyImage = image
  .addBands([ndvi, ndwi, mndwi, ndbi])
  .toFloat();

print('Output bands:', classifyImage.bandNames());
Map.addLayer(image, {bands: ['Red', 'Green', 'Blue'], min: 0, max: 0.3}, 'RGB');
Map.addLayer(image, {bands: ['NIR', 'Red', 'Green'], min: 0, max: 0.4}, 'False Color');
Map.addLayer(ndvi, {min: -1, max: 1, palette: ['white', 'yellow', 'green']}, 'NDVI');
Map.addLayer(mndwi, {min: -1, max: 1, palette: ['brown', 'white', 'blue']}, 'MNDWI');

var exportName = 'Mining_Sentinel2_LULC_Input_' + year;
var exportOptions = {
  image: classifyImage.unmask({value: noDataValue, sameFootprint: false}),
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

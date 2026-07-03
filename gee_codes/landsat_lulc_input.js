/*****************************************
全国矿区 Landsat 土地利用分类输入影像
数据源：Landsat 5 / 7 / 8 / 9 Collection 2 Level 2
输出：Blue、Green、Red、NIR、SWIR1、SWIR2、NDVI、NDWI、MNDWI、NDBI
******************************************/

// ===============================
// 1. 用户参数
// ===============================

var roiAsset = 'users/your_username/your_mining_area';
var year = 2010;
var startMonth = 6;
var endMonth = 10;
var cloudCover = 30;
var exportFolder = 'Mining_LULC_Landsat';

// 建议为 PLUS 设置研究区所在的投影坐标系；null 表示使用影像默认投影。
var exportCrs = null;
var noDataValue = -9999;

if (year < 1984) {
  throw new Error('Landsat 5 Collection 2 不支持 1984 年以前的年份。');
}
if (startMonth < 1 || endMonth > 12 || startMonth > endMonth) {
  throw new Error('月份范围必须满足 1 <= startMonth <= endMonth <= 12。');
}

var roi = ee.FeatureCollection(roiAsset);
var startDate = ee.Date.fromYMD(year, startMonth, 1);
// filterDate 的结束日期不包含在内，因此推进到结束月份的下一个月。
var endDate = ee.Date.fromYMD(year, endMonth, 1).advance(1, 'month');

Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

// ===============================
// 2. 去云、饱和像元掩膜与缩放
// ===============================

function maskAndScaleLandsatL2(image) {
  // QA_PIXEL 低 6 位依次覆盖填充值、膨胀云、卷云/未使用、云、云影和雪。
  var qaMask = image.select('QA_PIXEL')
    .bitwiseAnd(parseInt('111111', 2))
    .eq(0);
  var saturationMask = image.select('QA_RADSAT').eq(0);

  var opticalBands = image.select('SR_B.*')
    .multiply(0.0000275)
    .add(-0.2);

  return image
    .addBands(opticalBands, null, true)
    .updateMask(qaMask)
    .updateMask(saturationMask)
    .copyProperties(image, image.propertyNames());
}

function renameL57(image) {
  return image.select(
    ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'],
    ['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2']
  );
}

function renameL89(image) {
  return image.select(
    ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'],
    ['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2']
  );
}

function getCollection(datasetId, renameFunction) {
  return ee.ImageCollection(datasetId)
    .filterBounds(roi)
    .filterDate(startDate, endDate)
    .filter(ee.Filter.lt('CLOUD_COVER', cloudCover))
    .map(maskAndScaleLandsatL2)
    .map(renameFunction);
}

// ===============================
// 3. 根据年份选择传感器
// ===============================

var collection;
var sensorLabel;

if (year <= 2011) {
  collection = getCollection('LANDSAT/LT05/C02/T1_L2', renameL57);
  sensorLabel = 'Landsat 5 TM';
} else if (year === 2012) {
  collection = getCollection('LANDSAT/LE07/C02/T1_L2', renameL57);
  sensorLabel = 'Landsat 7 ETM+（注意 SLC-off 条带）';
} else if (year <= 2021) {
  collection = getCollection('LANDSAT/LC08/C02/T1_L2', renameL89);
  sensorLabel = 'Landsat 8 OLI';
} else {
  var landsat8 = getCollection('LANDSAT/LC08/C02/T1_L2', renameL89);
  var landsat9 = getCollection('LANDSAT/LC09/C02/T1_L2', renameL89);
  collection = landsat8.merge(landsat9);
  sensorLabel = 'Landsat 8/9 OLI';
}

var imageCount = collection.size();
print('Sensor:', sensorLabel);
print('Date range:', startDate, endDate);
print('Landsat image count:', imageCount);

// 空集合时生成全掩膜占位影像，使脚本可运行并明确显示无有效数据。
var emptyImage = ee.Image.constant([0, 0, 0, 0, 0, 0])
  .rename(['Blue', 'Green', 'Red', 'NIR', 'SWIR1', 'SWIR2'])
  .updateMask(ee.Image(0));

var image = ee.Image(ee.Algorithms.If(
  imageCount.gt(0),
  collection.median(),
  emptyImage
)).clip(roi);

// 使用 expression 避免缩放后负反射率被 normalizedDifference 自动掩膜。
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

// ===============================
// 4. 导出 Cloud Optimized GeoTIFF
// ===============================

var exportName = 'Mining_Landsat_LULC_Input_' + year;
var exportOptions = {
  image: classifyImage.unmask({value: noDataValue, sameFootprint: false}),
  description: exportName,
  fileNamePrefix: exportName,
  folder: exportFolder,
  region: roi.geometry(),
  scale: 30,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true, noData: noDataValue}
};

if (exportCrs) {
  exportOptions.crs = exportCrs;
}

Export.image.toDrive(exportOptions);

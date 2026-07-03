/*****************************************
全国矿区 WorldPop 人口栅格下载
数据源：WorldPop Global Project 100 m（2000—2020）
输出：Population_Count（每像元人数）、Population_Density（人/km²）
适用于 PLUS 模型社会经济驱动因子。
******************************************/

var roiAsset = 'users/your_username/your_mining_area';
var year = 2020;
var exportFolder = 'Mining_Population';
var exportCrs = null;
var noDataValue = -9999;

if (year < 2000 || year > 2020) {
  throw new Error('WorldPop/GP/100m/pop 的年份应在 2000—2020 范围内。');
}

var roi = ee.FeatureCollection(roiAsset);
Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

// 同时按年份和研究区筛选；mosaic 可处理跨国或跨影像研究区，避免 first() 任取一景。
var collection = ee.ImageCollection('WorldPop/GP/100m/pop')
  .filterBounds(roi)
  .filter(ee.Filter.eq('year', year))
  .select('population');

var imageCount = collection.size();
print('WorldPop image count:', imageCount);

var emptyPopulation = ee.Image.constant(0)
  .rename('population')
  .updateMask(ee.Image(0));
var populationRaw = ee.Image(ee.Algorithms.If(
  imageCount.gt(0),
  collection.mosaic(),
  emptyPopulation
)).clip(roi);

var populationCount = populationRaw
  .rename('Population_Count')
  .toFloat();
var populationDensity = populationCount
  .divide(ee.Image.pixelArea())
  .multiply(1e6)
  .rename('Population_Density')
  .toFloat();
var populationImage = populationCount.addBands(populationDensity);

print('Output bands:', populationImage.bandNames());
Map.addLayer(
  populationDensity,
  {min: 0, max: 5000, palette: ['white', 'yellow', 'orange', 'red']},
  'Population Density_' + year
);

var exportName = 'Mining_Population_' + year;
var exportOptions = {
  image: populationImage.unmask({value: noDataValue, sameFootprint: false}),
  description: exportName,
  fileNamePrefix: exportName,
  folder: exportFolder,
  region: roi.geometry(),
  scale: 100,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true, noData: noDataValue}
};

if (exportCrs) {
  exportOptions.crs = exportCrs;
}

Export.image.toDrive(exportOptions);

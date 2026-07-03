/*****************************************
全国矿区 DEM、坡度下载
数据源：NASA SRTM V3 30 m（约 60°N—56°S）
输出：DEM（m）、Slope（degree）
******************************************/

var roiAsset = 'users/your_username/your_mining_area';
var exportFolder = 'Mining_Topography';
var exportCrs = null;
var noDataValue = -9999;

var roi = ee.FeatureCollection(roiAsset);
Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

// 先在完整 DEM 上计算坡度，再裁剪，避免研究区边界产生人为边缘。
var sourceDem = ee.Image('USGS/SRTMGL1_003').select('elevation');
var dem = sourceDem.rename('DEM').clip(roi).toFloat();
var slope = ee.Terrain.slope(sourceDem).rename('Slope').clip(roi).toFloat();
var terrain = dem.addBands(slope).toFloat();

print('Output bands:', terrain.bandNames());
Map.addLayer(
  dem,
  {min: 0, max: 1000, palette: ['blue', 'cyan', 'green', 'yellow', 'orange', 'red']},
  'DEM'
);
Map.addLayer(
  slope,
  {min: 0, max: 30, palette: ['white', 'yellow', 'orange', 'red']},
  'Slope'
);

var exportOptions = {
  image: terrain.unmask({value: noDataValue, sameFootprint: false}),
  description: 'Mining_DEM_Slope_30m',
  fileNamePrefix: 'Mining_DEM_Slope_30m',
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

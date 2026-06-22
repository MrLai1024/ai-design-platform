const { merge } = require('webpack-merge');
const common = require('./webpack.common');
module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-cheap-module-source-map',
  devServer: {
    port: 8002,
    hot: true,
    open: false,
    historyApiFallback: true,
    headers: { 'Access-Control-Allow-Origin': '*' },
  },
});

const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { VueLoaderPlugin } = require('vue-loader');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';
const appName = 'ai-generation-app';

module.exports = {
  ignoreWarnings: [
    // @vue/compiler-sfc browser ESM build contains dynamic require() for
    // Node-only features (source-map, postcss) that gracefully degrade at runtime.
    /Critical dependency: require function is used in a way/,
  ],
  entry: path.resolve(__dirname, '../src/main.ts'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    library: `${appName}-[name]`,
    libraryTarget: 'umd',
    globalObject: 'window',
    publicPath: isDev ? '//localhost:8002/' : '/',
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.vue', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../micro-core/src'),
    },
  },
  module: {
    rules: [
      { test: /\.vue$/, use: 'vue-loader' },
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: { appendTsSuffixTo: [/\.vue$/], transpileOnly: true },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: [
          isDev ? 'vue-style-loader' : MiniCssExtractPlugin.loader,
          'css-loader',
          'postcss-loader',
        ],
      },
      { test: /\.(png|jpe?g|gif|svg|webp)$/i, type: 'asset/resource' },
      { test: /\.(woff2?|eot|ttf|otf)$/i, type: 'asset/resource' },
    ],
  },
  plugins: [
    new VueLoaderPlugin(),
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Generation',
    }),
    ...(isDev ? [] : [new MiniCssExtractPlugin({ filename: 'css/[name].[contenthash:8].css' })]),
  ],
};

const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');

const isDev = process.env.NODE_ENV === 'development';
const appName = 'ai-workflow';

module.exports = {
  entry: path.resolve(__dirname, '../src/main.tsx'),
  output: {
    path: path.resolve(__dirname, '../dist'),
    filename: 'js/[name].[contenthash:8].js',
    library: `${appName}-[name]`,
    libraryTarget: 'umd',
    globalObject: 'window',
    publicPath: isDev ? '//localhost:8003/' : '/',
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.jsx', '.js', '.json'],
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@ai-design/shared': path.resolve(__dirname, '../../shared/src'),
      '@ai-design/micro-core': path.resolve(__dirname, '../../micro-core/src'),
    },
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: { loader: 'ts-loader', options: { transpileOnly: true } },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        oneOf: [
          {
            resourceQuery: /module/,
            use: [
              isDev ? 'style-loader' : MiniCssExtractPlugin.loader,
              {
                loader: 'css-loader',
                options: { modules: { localIdentName: '[local]_[hash:base64:8]' } },
              },
              'postcss-loader',
            ],
          },
          {
            use: [
              isDev ? 'style-loader' : MiniCssExtractPlugin.loader,
              'css-loader',
              'postcss-loader',
            ],
          },
        ],
      },
      { test: /\.(png|jpe?g|gif|svg|webp)$/i, type: 'asset/resource' },
      { test: /\.(woff2?|eot|ttf|otf)$/i, type: 'asset/resource' },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: path.resolve(__dirname, '../public/index.html'),
      title: 'AI Workflow',
    }),
    ...(isDev ? [] : [new MiniCssExtractPlugin({ filename: 'css/[name].[contenthash:8].css' })]),
  ],
};

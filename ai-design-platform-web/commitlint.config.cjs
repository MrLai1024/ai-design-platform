module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', [
      'feat',
      'fix',
      'refactor',
      'style',
      'docs',
      'test',
      'chore',
      'perf',
      'ci',
      'build',
    ]],
    'subject-case': [0],
  },
};

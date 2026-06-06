/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json', 'node'],
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      tsconfig: {
        target: 'ES2022',
        module: 'commonjs',
        esModuleInterop: true,
        skipLibCheck: true,
        strict: true,
        resolveJsonModule: true
      }
    }]
  },
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.d.ts'
  ],
  coverageDirectory: 'coverage',
  verbose: true,
  testTimeout: 30000
};

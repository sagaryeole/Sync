import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import ts from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';

export default [
  // Without this, `eslint .` lints the minified production bundle in dist/
  // and reports hundreds of meaningless errors in generated code, which
  // both hides real source problems and makes the lint gate unpassable.
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**', '*.config.js'],
  },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2020,
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        React: 'readonly',
        WebSocket: 'readonly',
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        fetch: 'readonly',
        setTimeout: 'readonly',
        setInterval: 'readonly',
        clearTimeout: 'readonly',
        clearInterval: 'readonly',
        URLSearchParams: 'readonly',
        HTMLDivElement: 'readonly',
      },
    },
    plugins: {
      '@typescript-eslint': ts,
      react,
      'react-hooks': reactHooks,
    },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      ...ts.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    // Presentation code renders untrusted network data. A raw `.toFixed()`
    // on a null/NaN field throws during render, and React unmounts the whole
    // tree on a render throw — one bad API field white-screens the terminal.
    // The formatters in src/lib/format.ts return an em dash instead.
    files: ['src/components/**/*.{ts,tsx}', 'src/pages/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.property.name='toFixed']",
          message:
            'Do not call .toFixed() directly on network data — it throws on null/NaN and takes down the page. Use fmtUsd/fmtNum/fmtPct/fmtQty from src/lib/format.ts.',
        },
      ],
    },
  },
];

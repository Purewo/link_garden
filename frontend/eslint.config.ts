// ESLint flat config (ESLint 9). Generated TS types are excluded from linting.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'
import prettier from 'eslint-config-prettier'

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/shared/api/schema.d.ts',
      'openapi/schema.json',
      '**/*.cjs',
      // Legacy JS scaffolding from the pre-TS app. Other units replace these
      // in-place; until the integrator merges, exclude them from lint so the
      // new files can be enforced strictly.
      'vite.config.js',
      'src/main.js',
      'src/style.css',
      'src/components/HelloWorld.vue',
      'src/components/MilkdownEditor.vue',
      'src/views/AdminPublishView.vue',
      'src/views/AdminView.vue',
      'src/views/DetailView.vue',
      'src/views/HomeView.vue',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  ...vue.configs['flat/recommended'],
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.vue'],
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        localStorage: 'readonly',
        navigator: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
        URLSearchParams: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        FormData: 'readonly',
        File: 'readonly',
        Blob: 'readonly',
        HTMLElement: 'readonly',
        Event: 'readonly',
        CustomEvent: 'readonly',
        AbortController: 'readonly',
      },
    },
    rules: {
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { attributes: false } },
      ],
      'vue/multi-word-component-names': 'off',
      'vue/component-api-style': ['error', ['script-setup']],
      // Optional props naturally lack defaults in TS-first SFCs; the typing is
      // the contract.
      'vue/require-default-prop': 'off',
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        sourceType: 'module',
      },
    },
  },
  {
    files: ['scripts/**/*.ts', 'vite.config.ts', 'eslint.config.ts'],
    languageOptions: {
      globals: {
        process: 'readonly',
        Buffer: 'readonly',
        __dirname: 'readonly',
        require: 'readonly',
        module: 'readonly',
      },
    },
  },
  // eslint-config-prettier exports a typed shape that doesn't perfectly match
  // typescript-eslint's flat-config schema; the value is correct at runtime.
  // eslint-disable-next-line @typescript-eslint/no-unsafe-argument
  prettier,
)

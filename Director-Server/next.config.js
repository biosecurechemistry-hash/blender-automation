/** @type {import('next').NextConfig} */
const path = require('path');

const nextConfig = {
  // -----------------------------------------------------------------------
  // Island strategy: force all resolution into ~/Director-Server.
  // The parent monorepo had broken packages/agents symlinks — we ignore
  // them completely and treat this directory as the sole root.
  // -----------------------------------------------------------------------
  reactStrictMode: true,

  // Never look outside this project for node_modules or workspace packages.
  webpack: (config, { isServer }) => {
    // --- Resolve modules ONLY from this project's node_modules ---
    config.resolve.modules = [
      path.resolve(__dirname, 'node_modules'),
    ];

    // Explicitly block resolution of any external workspace symlinks
    // that may still be dangling from the broken monorepo.
    config.resolve.symlinks = false;

    // --- Resolve aliases to local paths ---
    config.resolve.alias = {
      // Force React to a single instance — prevents hooks errors from
      // duplicate React copies leaked via old workspace links.
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),

      // Local project aliases
      '@director/lib': path.resolve(__dirname, 'lib'),
      '@director/pages': path.resolve(__dirname, 'pages'),
    };

    // --- Ignore external workspace directories completely ---
    // If the monorepo root or packages/* still exist on disk and
    // Webpack tries to traverse them, these exclusions block it.
    const monorepoRoot = path.resolve(__dirname, '..');
    config.watchOptions = {
      ...config.watchOptions,
      ignored: [
        path.join(monorepoRoot, 'packages'),
        path.join(monorepoRoot, 'node_modules'),
        path.join(monorepoRoot, '.git'),
        '**/node_modules/**',
      ],
    };

    // --- Server-side externals: never bundle pg driver ---
    if (isServer) {
      config.externals = [
        ...(Array.isArray(config.externals) ? config.externals : []),
        'pg',
        'pg-native',
        'dns',
        'net',
        'tls',
        'fs',
      ];
    }

    return config;
  },

  // --- Environment variables exposed to the browser ---
  env: {
    NEXT_PUBLIC_OPEN_WEBUI_URL: process.env.OPEN_WEBUI_URL || 'http://127.0.0.1:3333',
    NEXT_PUBLIC_ZEROCLAW_URL: process.env.ZEROCLAW_URL || 'http://127.0.0.1:42617/agent',
    NEXT_PUBLIC_BLENDER_API: process.env.BLENDER_API || 'http://127.0.0.1:5000',
  },
};

module.exports = nextConfig;

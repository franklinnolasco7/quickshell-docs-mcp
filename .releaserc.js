const notesPattern = (sel) => new RegExp(`^[\\s|*]*(${sel}):\\s*(.*)`, "i");

module.exports = {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      {
        parserOpts: {
          headerPattern: "^([\\w.\\-*/]+):\\s?(.*)$",
          headerCorrespondence: ["scope", "subject"],
          noteKeywords: ["BREAKING CHANGE", "Semver"],
          notesPattern,
        },
        releaseRules: [
          { notes: [{ title: "Semver", text: "minor" }], release: "minor" },
          { notes: [{ title: "Semver", text: "major" }], release: "major" },
        ],
      },
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        parserOpts: {
          headerPattern: "^([\\w.\\-*/]+):\\s?(.*)$",
          headerCorrespondence: ["scope", "subject"],
          noteKeywords: null,
        },
      },
    ],
    [
      "@google/semantic-release-replace-plugin",
      {
        replacements: [
          {
            files: ["pyproject.toml"],
            from: "version = \"[0-9]+\\.[0-9]+\\.[0-9]+[^\"]*\"",
            to: "version = \"${nextRelease.version}\"",
            results: [{ file: "pyproject.toml", hasChanged: true }],
          },
        ],
      },
    ],
    [
      "@semantic-release/git",
      {
        assets: ["pyproject.toml"],
        message: "release: v${nextRelease.version} [skip ci]",
      },
    ],
    [
      "@semantic-release/exec",
      {
        prepareCmd:
          'echo "released=true" >> "$GITHUB_OUTPUT" && echo "version=${nextRelease.version}" >> "$GITHUB_OUTPUT"',
      },
    ],
    "@semantic-release/github",
  ],
};
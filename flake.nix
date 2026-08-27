{
  description =
    "MCP server exposing live Quickshell documentation from quickshell.org";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      # x86_64-darwin is gone from nixpkgs 26.11; declaring it here makes
      # `nix flake check` fail on runners even though this package targets Linux.
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      forAllSystems = f:
        builtins.listToAttrs (map (s: { name = s; value = f s; }) systems);
      pkgVersion =
        (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
    in
    {
      packages = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in rec {
          quickshell-mcp = pkgs.python3Packages.buildPythonApplication {
            pname = "quickshell-mcp";
            version = pkgVersion;
            pyproject = true;
            src = self;
            build-system = [ pkgs.python3Packages.hatchling ];
            dependencies = with pkgs.python3Packages; [
              mcp
              httpx
              beautifulsoup4
              markdownify
            ];
            # Offline unit suite lives in ./tests; run via devShell instead.
            doCheck = false;
          };
          default = quickshell-mcp;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program =
            "${self.packages.${system}.default}/bin/quickshell-mcp";
        };
      });

      devShells = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.mkShell {
            # All members come from python3Packages, which places its own
            # interpreter on PATH; do not add `python3` explicitly (rejected
            # by nixpkgs' python package checks).
            packages = with pkgs.python3Packages; [
              mcp
              httpx
              beautifulsoup4
              markdownify
              hatchling
              pytest
              pytest-cov
              pytest-xdist
              ruff
              mypy
              build
              twine
            ];
          };
        });
    };
}

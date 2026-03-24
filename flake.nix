{
  description = "ClawMama development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.firecracker
            pkgs.e2fsprogs
            pkgs.curl
          ];

          shellHook = ''
            # Create symlink to firecracker in ~/.local/bin if it doesn't exist
            mkdir -p "$HOME/.local/bin"
            if [ ! -e "$HOME/.local/bin/firecracker" ]; then
              ln -s ${pkgs.firecracker}/bin/firecracker "$HOME/.local/bin/firecracker"
            fi

            # Download Firecracker kernel if not present
            KERNEL_PATH="$HOME/.local/share/clawmama/vmlinux"
            if [ ! -f "$KERNEL_PATH" ]; then
              mkdir -p "$HOME/.local/share/clawmama"
              echo "Downloading Firecracker kernel..."
              curl -sL https://s3.amazonaws.com/spec.ccfc.min/img/ubuntu/vmlinuz -o "$KERNEL_PATH"
              chmod 644 "$KERNEL_PATH"
            fi
          '';
        };
      }
    );
}

{
  description = "Pinned Hiro boot image build environment";
  inputs.nixpkgs.url = "github:nixos/nixpkgs/c5ae371f1a6a7fd27823bc500d9390b38c05fa55";
  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      diskTools = with pkgs; [ cryptsetup dosfstools e2fsprogs mtools squashfsTools zstd ];
      builder = pkgs.mkosi.override { extraDeps = diskTools ++ [ pkgs.apt pkgs.dpkg pkgs.gnupg ]; };
      search = pkgs.buildEnv {
        name = "hiro-image-tools";
        paths = builder.dependencies;
        pathsToLink = [ "/bin" ];
        ignoreCollisions = true;
      };
      mkosi = pkgs.writeShellScriptBin "mkosi" ''
        exec ${builder}/bin/mkosi --extra-search-path=${search}/bin "$@"
      '';
    in {
      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [ mkosi qemu_test apt dpkg binutils util-linux gptfdisk
          (python3.withPackages (ps: [ ps.pyyaml ])) go git gzip gnutar coreutils gh ] ++ diskTools;
        HIRO_OVMF = "${pkgs.OVMF.fd}/FV/OVMF_CODE.fd";
        HIRO_OVMF_VARS = "${pkgs.OVMF.fd}/FV/OVMF_VARS.fd";
      };
    };
}

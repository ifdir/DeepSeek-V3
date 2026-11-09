#!/bin/bash
# Stand 11: Android-aarch64-Variante (Termux) des gepruefte Linux-Produktpakets bauen.
# Einzige plattformabhaengige Datei im Paket ist matrix_api/native/libmatrix_boundary_core.so (Rust-Kern, ABI 3).
# Sie wird aus der Crate DES PAKETS fuer aarch64-linux-android neu gebaut; alles andere bleibt byte-gleich.
# Kein NDK verfuegbar -> Zig/lld als Linker; bionic wird NICHT eingebaut, sondern per DT_NEEDED
# (libc.so, libdl.so, libm.so, liblog.so) zur Laufzeit von Android geliefert; LLVM-libunwind statisch.
# Keine Produktcode-Aenderung. Aufruf: baue_android_11.sh <linux-paket.zip> <ausgabeordner>
set -euo pipefail
LZIP=$(realpath "$1"); OUT=$(realpath -m "$2"); mkdir -p "$OUT"
HIER=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d /tmp/android11_XXXXXX)
trap 'rm -rf "$W"' EXIT

rustup target add aarch64-linux-android >/dev/null
python3 -m venv "$W/zigenv"
"$W/zigenv/bin/pip" install -q "ziglang==0.17.1"
ZIG=$("$W/zigenv/bin/python" -c "import ziglang,os;print(os.path.join(os.path.dirname(ziglang.__file__),'zig'))")
U=$(dirname "$ZIG")/lib/libunwind

# 1) Platzhalter-Bibliotheken nur fuer die Android-sonames (Inhalt leer; zur Laufzeit liefert Android die echten)
mkdir -p "$W/stub"; : > "$W/stub/empty.c"
for l in c dl m log; do
  "$ZIG" cc -target aarch64-linux-musl -shared -nostdlib -fPIC -Wl,-soname,lib$l.so -o "$W/stub/lib$l.so" "$W/stub/empty.c"
done

# 2) LLVM-libunwind statisch (errno-Zugriff auf bionic-Namen __errno abgebildet)
mkdir -p "$W/unwind"
F=(-target aarch64-linux-musl -fPIC -O2 -c -I"$U/include" -D_LIBUNWIND_IS_NATIVE_ONLY -DNDEBUG -funwind-tables
   -fvisibility=hidden -D__errno_location=__errno)
for s in "$U"/src/*.c "$U"/src/*.cpp "$U"/src/*.S; do
  b=$(basename "$s"); case "$b" in Unwind-EHABI.cpp|Unwind-seh.cpp|Unwind-wasm.c) continue;; esac
  case "$b" in *.cpp) "$ZIG" c++ "${F[@]}" -fno-exceptions -fno-rtti -nostdinc++ -std=c++17 "$s" -o "$W/unwind/$b.o";;
               *)     "$ZIG" cc  "${F[@]}" "$s" -o "$W/unwind/$b.o";; esac
done
"$ZIG" ar rcs "$W/unwind/libunwind.a" "$W"/unwind/*.o

# 3) Linker-Wrapper
cat > "$W/linker.sh" <<EOF
#!/bin/bash
args=()
for a in "\$@"; do case "\$a" in -lc|-ldl|-lm|-llog|-lunwind) ;; *) args+=("\$a");; esac; done
exec "$ZIG" cc -target aarch64-linux-musl "\${args[@]}" "$W/unwind/libunwind.a" -Wl,--no-as-needed \
  "$W/stub/libc.so" "$W/stub/libdl.so" "$W/stub/libm.so" "$W/stub/liblog.so"
EOF
chmod +x "$W/linker.sh"

# 4) Linux-Paket entpacken, Crate des Pakets fuer Android bauen, .so ersetzen
mkdir "$W/pkg"; (cd "$W/pkg" && unzip -q "$LZIP")
LNAME=$(ls "$W/pkg"); ROOT="$W/pkg/$LNAME"
KURZ=${LNAME##*_}
cp -r "$ROOT/native_core/matrix-boundary-core" "$W/crate"; rm -rf "$W/crate/target"
(cd "$W/crate" && CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$W/linker.sh" \
   cargo build --release --offline --locked --target aarch64-linux-android -q)
SO="$W/crate/target/aarch64-linux-android/release/libmatrix_boundary_core.so"

# 5) statische Pruefung der Bibliothek (kein Geraet verfuegbar)
readelf -h "$SO" | grep -q "AArch64" || { echo "ABBRUCH: nicht aarch64"; exit 3; }
NEED=$(readelf -d "$SO" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | tr '\n' ' ')
[ "$NEED" = "libc.so libdl.so liblog.so libm.so " ] || { echo "ABBRUCH: NEEDED=$NEED"; exit 3; }
EXP=$(nm -D --defined-only "$SO" | awk '{print $3}' | sort | tr '\n' ' ')
[ "$EXP" = "matrix_boundary_abi_version matrix_boundary_check " ] || { echo "ABBRUCH: Exporte=$EXP"; exit 3; }
nm -D --undefined-only "$SO" | grep -q "__errno_location" && { echo "ABBRUCH: musl-Symbol"; exit 3; }
readelf -lW "$SO" | grep -q " TLS " && { echo "ABBRUCH: TLS-Segment"; exit 3; }
UNDEF=$(nm -D --undefined-only "$SO" | awk '{print $2}' | tr '\n' ' ')

NAME="MATRIX10_STAND11D_PRODUKT_android-aarch64_$KURZ"
mv "$ROOT" "$W/pkg/$NAME"; ROOT="$W/pkg/$NAME"
cp "$SO" "$ROOT/matrix_api/native/libmatrix_boundary_core.so"
python3 -I - "$ROOT" "$LZIP" "$UNDEF" <<'PY'
import hashlib, json, sys
from pathlib import Path
root, lzip, undef = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
st = json.loads((root / "MATRIX10_STAND11_STATUS.json").read_text())
st.update({
    "plattform": "android-aarch64 (Termux)",
    "nur_getestet_auf": "NICHTS auf Android. Nur statisch geprueft (ELF aarch64, NEEDED bionic-Namen, Exporte, keine musl-Symbole, kein TLS). "
                        "Alle uebrigen Pruefungen gelten fuer das identische Linux-x86_64-Paket.",
    "android_status": "GEBAUT, AUF ANDROID UNGETESTET",
    "abgeleitet_von_linux_paket": {"datei": lzip.name, "sha256": sha(lzip)},
    "einzige_abweichung_zum_linux_paket": "nur matrix_api/native/libmatrix_boundary_core.so (aarch64-linux-android) und die Android-Felder in dieser STATUS.json",
    "rust_bibliothek_sha256": sha(root / "matrix_api/native/libmatrix_boundary_core.so"),
    "rust_bibliothek_bionic_symbole": undef,
    "android_build": "ARBEITSSTAND_11/tools/baue_android_11.sh (Zig 0.17.1 als Linker, LLVM-libunwind statisch, kein NDK)",
})
(root / "MATRIX10_STAND11_STATUS.json").write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")
PY
(cd "$W/pkg" && find "$NAME" -type f | LC_ALL=C sort | zip -q -X "$OUT/$NAME.zip" -@)
(cd "$OUT" && sha256sum "$NAME.zip" > "$NAME.zip.sha256" && cat "$NAME.zip.sha256")

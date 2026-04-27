// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "LlamaFrameworkPackage",
    platforms: [
        .iOS(.v16)
    ],
    products: [
        .library(
            name: "llama",
            targets: ["llama"]
        )
    ],
    targets: [
        .binaryTarget(
            name: "llama",
            url: "https://github.com/ggml-org/llama.cpp/releases/download/b8946/llama-b8946-xcframework.zip",
            checksum: "896a65ac7c245317d7a49ea0b6e898424237b55b30618426fa43ff0bf16cdebc"
        )
    ]
)

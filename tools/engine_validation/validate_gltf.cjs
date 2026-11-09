// Validate actual binary skins and animation using Khronos's independent implementation.
const fs = require("fs");
const path = require("path");
const validator = require(path.resolve("build/validation-tools/gltf/node_modules/gltf-validator"));

async function main() {
    const file = process.argv[2];
    const report = await validator.validateBytes(new Uint8Array(fs.readFileSync(file)), {
        uri: path.basename(file), maxIssues: 10000, writeTimestamp: false
    });
    fs.writeFileSync(file + ".validation.json", JSON.stringify(report, null, 2));
    const issues = report.issues;
    console.log(JSON.stringify({ errors: issues.numErrors, warnings: issues.numWarnings,
        messages: issues.messages.filter(m => m.severity <= 1).slice(0, 8) }));
    process.exitCode = issues.numErrors ? 1 : 0;
}
main().catch(error => { console.error(error); process.exitCode = 1; });

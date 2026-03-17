const fs = require('fs');
const path = require('path');

function searchFiles(dir, pattern) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const fullPath = path.join(dir, file);
        if (fs.statSync(fullPath).isDirectory()) {
            if (file !== 'node_modules' && file !== '.git') {
                searchFiles(fullPath, pattern);
            }
        } else {
            try {
                const content = fs.readFileSync(fullPath, 'utf8');
                if (content.includes(pattern)) {
                    console.log('FOUND in:', fullPath);
                    const lines = content.split('\n');
                    lines.forEach((line, i) => {
                        if (line.includes(pattern)) {
                            console.log(`  Line ${i + 1}: ${line.trim()}`);
                        }
                    });
                }
            } catch (e) {
                // Ignore binary files
            }
        }
    }
}

const startDir = process.cwd();
console.log('Searching for "Max retries reached" in:', startDir);
searchFiles(startDir, 'Max retries reached');
console.log('Search finished.');

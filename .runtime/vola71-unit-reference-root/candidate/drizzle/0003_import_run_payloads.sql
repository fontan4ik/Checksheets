ALTER TABLE `import_items` ADD `supplier_json` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE `import_items` ADD `payload_json` text;--> statement-breakpoint
ALTER TABLE `import_runs` ADD `records_json` text DEFAULT '[]' NOT NULL;
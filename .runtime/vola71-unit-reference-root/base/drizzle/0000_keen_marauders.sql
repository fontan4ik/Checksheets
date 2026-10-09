CREATE TABLE `operator_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`article` text NOT NULL,
	`event_type` text NOT NULL,
	`detail_json` text DEFAULT '{}' NOT NULL,
	`created_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `operator_records` (
	`article` text PRIMARY KEY NOT NULL,
	`listing_article` text NOT NULL,
	`supplier_json` text DEFAULT '{}' NOT NULL,
	`overrides_json` text DEFAULT '{}' NOT NULL,
	`validation_json` text DEFAULT 'null' NOT NULL,
	`updated_at` text NOT NULL
);

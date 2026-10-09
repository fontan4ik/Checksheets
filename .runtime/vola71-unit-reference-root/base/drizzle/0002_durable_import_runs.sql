CREATE TABLE `import_items` (
	`run_id` text NOT NULL,
	`article` text NOT NULL,
	`listing_article` text NOT NULL,
	`status` text NOT NULL,
	`stage` text NOT NULL,
	`error_json` text,
	`product_id` text,
	`ozon_task_id` text,
	`attempts` integer DEFAULT 0 NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `import_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`principal_id` text NOT NULL,
	`idempotency_key` text NOT NULL,
	`status` text NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint

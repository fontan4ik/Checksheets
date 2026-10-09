CREATE TABLE `supplier_refresh_control` (
	`id` integer PRIMARY KEY NOT NULL CHECK (`id` = 1),
	`last_started_at` integer,
	`lease_token` text,
	`lease_expires_at` integer
);
--> statement-breakpoint
INSERT INTO `supplier_refresh_control` (`id`, `last_started_at`, `lease_token`, `lease_expires_at`) VALUES (1, NULL, NULL, NULL);

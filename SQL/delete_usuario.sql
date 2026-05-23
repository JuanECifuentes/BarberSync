BEGIN;

-- 1. Eliminar facturas
DELETE FROM billing_invoice 
WHERE user_id = 9 
   OR organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 2. Eliminar suscripciones
DELETE FROM billing_subscription 
WHERE user_id = 9 
   OR organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 3. Eliminar notificaciones
DELETE FROM notifications_log
WHERE appointment_id IN (
    SELECT id FROM scheduling_appointment 
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

-- 4. Eliminar servicios de citas
DELETE FROM scheduling_appointment_service
WHERE appointment_id IN (
    SELECT id FROM scheduling_appointment 
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

-- 5. Eliminar intervencion_producto PRIMERO (FK a intervencion_servicio y a intervencion)
DELETE FROM scheduling_intervencion_producto
WHERE intervencion_id IN (
    SELECT id FROM scheduling_intervencion
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    ) OR barber_id IN (
        SELECT id FROM accounts_barber_profile 
        WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
    )
);

-- 6. Eliminar intervencion_servicio
DELETE FROM scheduling_intervencion_servicio
WHERE intervencion_id IN (
    SELECT id FROM scheduling_intervencion
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    ) OR barber_id IN (
        SELECT id FROM accounts_barber_profile 
        WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
    )
);

-- 7. Eliminar intervenciones
DELETE FROM scheduling_intervencion
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR barber_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

-- 8. Eliminar ventas (finance_sale tiene FK a scheduling_appointment)
DELETE FROM finance_sale_item
WHERE sale_id IN (
    SELECT id FROM finance_sale
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

DELETE FROM finance_sale
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

-- 9. Eliminar citas
DELETE FROM scheduling_appointment
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR barber_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

-- 10. Eliminar servicio_producto
DELETE FROM scheduling_servicio_producto
WHERE servicio_id IN (
    SELECT id FROM scheduling_service
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

-- 11. Eliminar historial config barbero
DELETE FROM scheduling_historial_config_barbero
WHERE barber_service_id IN (
    SELECT id FROM scheduling_barber_service
    WHERE service_id IN (
        SELECT id FROM scheduling_service
        WHERE barbershop_id IN (
            SELECT id FROM accounts_barbershop 
            WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
        )
    ) OR barber_id IN (
        SELECT id FROM accounts_barber_profile 
        WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
    )
);

-- 12. Eliminar barber_service
DELETE FROM scheduling_barber_service
WHERE service_id IN (
    SELECT id FROM scheduling_service
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
) OR barber_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

-- 13. Eliminar historial precios servicio
DELETE FROM scheduling_historial_precio_servicio
WHERE service_id IN (
    SELECT id FROM scheduling_service
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

-- 14. Eliminar servicios
DELETE FROM scheduling_service
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

-- 15. Eliminar categorias servicio
DELETE FROM scheduling_categoria_servicio
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

-- 16. Eliminar horarios y excepciones
DELETE FROM scheduling_work_schedule
WHERE barber_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

DELETE FROM scheduling_exception
WHERE barber_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

-- 17. Eliminar inventario
DELETE FROM inventory_movement_item
WHERE product_id IN (
    SELECT id FROM inventory_product
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

DELETE FROM inventory_stock_movement
WHERE product_id IN (
    SELECT id FROM inventory_product
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

DELETE FROM inventory_historial_precio_producto
WHERE product_id IN (
    SELECT id FROM inventory_product
    WHERE barbershop_id IN (
        SELECT id FROM accounts_barbershop 
        WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
    )
);

DELETE FROM inventory_product
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

DELETE FROM inventory_movement
WHERE barbershop_origin_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR barbershop_destiny_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

DELETE FROM inventory_category
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 18. Eliminar clientes
DELETE FROM clients_ficha_clinica
WHERE client_id IN (
    SELECT id FROM clients_client
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

DELETE FROM clients_client
WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 19. Eliminar invitaciones
DELETE FROM accounts_organization_invitation_sucursales
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR organizationinvitation_id IN (
    SELECT id FROM accounts_organization_invitation
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

DELETE FROM accounts_organization_invitation
WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 20. Eliminar relaciones M2M barberos/membresías
DELETE FROM accounts_barber_profile_sucursales
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR barberprofile_id IN (
    SELECT id FROM accounts_barber_profile 
    WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
);

DELETE FROM accounts_membership_sucursales
WHERE barbershop_id IN (
    SELECT id FROM accounts_barbershop 
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
) OR membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9);

-- 21. Eliminar perfiles de barbero
DELETE FROM accounts_barber_profile
WHERE membership_id IN (SELECT id FROM accounts_membership WHERE user_id = 9)
OR membership_id IN (
    SELECT id FROM accounts_membership
    WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9)
);

-- 22. Eliminar membresías
DELETE FROM accounts_membership
WHERE user_id = 9 
   OR organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 23. Eliminar sucursales
DELETE FROM accounts_barbershop
WHERE organization_id IN (SELECT id FROM accounts_organization WHERE owner_id = 9);

-- 24. Eliminar organización
DELETE FROM accounts_organization 
WHERE owner_id = 9;

-- 25. SET NULL en campos de auditoría
UPDATE core_audit_log SET user_id = NULL WHERE user_id = 9;
UPDATE clients_client SET user_id = NULL WHERE user_id = 9;
UPDATE clients_client SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE clients_client SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE clients_ficha_clinica SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE clients_ficha_clinica SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE billing_plan_price SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE billing_invoice SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_categoria_servicio SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_categoria_servicio SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_service SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_service SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_historial_precio_servicio SET changed_by_id = NULL WHERE changed_by_id = 9;
UPDATE scheduling_barber_service SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_barber_service SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_historial_config_barbero SET changed_by_id = NULL WHERE changed_by_id = 9;
UPDATE scheduling_work_schedule SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_work_schedule SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_exception SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_exception SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_appointment SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_appointment SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE scheduling_intervencion SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE scheduling_intervencion SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE finance_sale SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE finance_sale SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE inventory_category SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE inventory_category SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE inventory_product SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE inventory_product SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE inventory_historial_precio_producto SET changed_by_id = NULL WHERE changed_by_id = 9;
UPDATE inventory_stock_movement SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE inventory_stock_movement SET updated_by_id = NULL WHERE updated_by_id = 9;
UPDATE inventory_movement SET created_by_id = NULL WHERE created_by_id = 9;
UPDATE inventory_movement SET updated_by_id = NULL WHERE updated_by_id = 9;

-- 26. Tablas que faltaban en el script original
DELETE FROM django_admin_log WHERE user_id = 9;
DELETE FROM accounts_user_groups WHERE user_id = 9;
DELETE FROM accounts_user_user_permissions WHERE user_id = 9;

-- 27. Tokens y cuentas sociales
DELETE FROM socialaccount_socialtoken WHERE account_id IN (SELECT id FROM socialaccount_socialaccount WHERE user_id = 9);
DELETE FROM socialaccount_socialaccount WHERE user_id = 9;
DELETE FROM account_emailaddress WHERE user_id = 9;

-- 28. Eliminar usuario
DELETE FROM accounts_user WHERE id = 9;

COMMIT;
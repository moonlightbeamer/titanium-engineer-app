# ── Virtual Network ───────────────────────────────────────────────────────────
# Required for private endpoint access to Azure OpenAI and to give ACA
# containers a routable path to that private endpoint.

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${local.prefix}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  address_space       = ["10.0.0.0/16"]
}

# ACA infrastructure subnet — /23 minimum required by Azure for ACA environments.
# Must be dedicated (no other resources) and delegated to Microsoft.App/environments.
resource "azurerm_subnet" "aca_infra" {
  name                 = "snet-aca-infra"
  resource_group_name  = data.azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.0.0/23"]

  delegation {
    name = "aca-env-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# Private endpoint subnet — hosts the Azure OpenAI private endpoint NIC.
resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = data.azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]
}

# ── Private DNS for Azure OpenAI ──────────────────────────────────────────────

resource "azurerm_private_dns_zone" "openai" {
  name                = "privatelink.openai.azure.com"
  resource_group_name = data.azurerm_resource_group.main.name
}

# Link the DNS zone to the VNet so ACA containers resolve the OpenAI hostname
# to the private endpoint IP instead of the public one.
resource "azurerm_private_dns_zone_virtual_network_link" "openai" {
  name                  = "pdnslink-openai"
  resource_group_name   = data.azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.openai.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
}

# ── Private Endpoint for Azure OpenAI ────────────────────────────────────────

resource "azurerm_private_endpoint" "openai" {
  name                = "pe-${local.prefix}-openai"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "psc-openai"
    private_connection_resource_id = azurerm_cognitive_account.openai.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  # Auto-registers the A record in the private DNS zone so hostname resolution
  # returns the private IP from within the VNet.
  private_dns_zone_group {
    name                 = "pdnsgroup-openai"
    private_dns_zone_ids = [azurerm_private_dns_zone.openai.id]
  }
}
